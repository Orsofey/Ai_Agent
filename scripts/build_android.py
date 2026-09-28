"""Build the Android client: APK (RuStore, direct install) and AAB (Google Play, RuStore); keep a stable signing key.

    BUILD_ANDROID.bat          — APK and AAB
    BUILD_ANDROID.bat aab      — only AAB
    BUILD_ANDROID.bat apk      — only APK
"""
import json
import os
import re
import time
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.storage import data_root

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT/'.build'/'android'


def run(args, cwd=None, env=None):
    values = [str(a) for a in args]
    # Flutter on Windows is a .bat entry point; command-shell use is build-time only.
    is_batch = os.name == 'nt' and values[0].lower().endswith(('.bat', '.cmd'))
    subprocess.run(values, cwd=cwd or ROOT, env=env, check=True, shell=is_batch)


def tool(name):
    if os.name == 'nt':
        # В папке flutter\bin рядом лежат bash-скрипт «flutter» и «flutter.bat». Python 3.12 может вернуть
        # первый, и Windows не запустит его: «[WinError 193] %1 is not a valid Win32 application».
        for ext in ('.bat', '.cmd', '.exe'):
            found = shutil.which(name + ext)
            if found:
                return found
    found = shutil.which(name)
    if found:
        return found
    if name == 'keytool':
        candidates = [Path(os.getenv('JAVA_HOME', '.'))/'bin/keytool.exe',
            Path(os.getenv('ProgramFiles', 'C:/Program Files'))/'Android/Android Studio/jbr/bin/keytool.exe']
        for p in candidates:
            if p.exists():
                return str(p)
    raise RuntimeError('Not found: '+name+'. Install Flutter / Android SDK / JDK and add tools to PATH.')


def signing():
    config = Path(os.getenv('LOCAL_AI_ANDROID_SIGNING', str(data_root()/'signing/android-signing.json')))
    if config.exists():
        value = json.loads(config.read_text(encoding='utf-8'))
        if not Path(value['storeFile']).is_file():
            raise RuntimeError('Signing keystore is missing. Restore it from your backup; do not replace it for existing APK users.')
        return value
    if os.getenv('LOCAL_AI_ANDROID_SIGNING'):
        raise RuntimeError('Specified signing config does not exist')
    config.parent.mkdir(parents=True, exist_ok=True)
    keystore = config.parent/'android-release.jks'
    if keystore.exists():
        raise RuntimeError('Keystore exists without config; restore its password/config instead of overwriting.')
    password = secrets.token_urlsafe(32)
    env = dict(os.environ, AGENT_KEYPASS=password)
    run([tool('keytool'), '-genkeypair', '-keystore', keystore, '-storetype', 'JKS', '-alias', 'localaiagent',
        '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000', '-storepass:env', 'AGENT_KEYPASS',
        '-keypass:env', 'AGENT_KEYPASS', '-dname', 'CN=Local AI Agent', '-noprompt'], env=env)
    value = dict(storeFile=str(keystore.resolve()), storePassword=password, keyPassword=password, keyAlias='localaiagent')
    config.write_text(json.dumps(value, indent=2), encoding='utf-8')
    try:
        config.chmod(0o600);keystore.chmod(0o600)
    except OSError:
        pass
    print('IMPORTANT: Back up your private signing folder (do not share it): '+str(config.parent))
    return value


REPOSITORY = 'https://dl.google.com/android/repository/'


def sdk_dir():
    """Папка Android SDK: из local.properties, созданного Flutter, переменных окружения или стандартного места."""
    props = TARGET/'android/local.properties'
    if props.exists():
        match = re.search(r'^sdk\.dir=(.+)$', props.read_text(encoding='utf-8', errors='replace'), re.M)
        if match:
            path = Path(match[1].strip().replace('\\:', ':').replace('\\\\', '\\'))
            if path.is_dir():
                return path
    for name in ('ANDROID_HOME', 'ANDROID_SDK_ROOT'):
        if os.getenv(name) and Path(os.environ[name]).is_dir():
            return Path(os.environ[name])
    for path in (Path(os.getenv('LOCALAPPDATA', '~'))/'Android/Sdk', Path.home()/'Library/Android/sdk', Path.home()/'Android/Sdk'):
        path = path.expanduser()
        if path.is_dir():
            return path
    return None


def required_ndk(flutter):
    """Версия NDK, которую просит Flutter (flutter.ndkVersion)."""
    tools = Path(flutter).resolve().parent.parent/'packages/flutter_tools/gradle'
    for source in sorted(tools.rglob('*')) if tools.is_dir() else []:
        if source.suffix in ('.kt', '.kts', '.groovy', '.gradle') and source.is_file():
            match = re.search(r'ndkVersion\s*(?::\s*String)?\s*=\s*"(\d+\.\d+\.\d+)"', source.read_text(encoding='utf-8', errors='ignore'))
            if match:
                return match[1]
    return None


def installed_ndks(sdk):
    folder = sdk/'ndk'
    found = [p.name for p in folder.iterdir() if (p/'source.properties').exists()] if folder.is_dir() else []
    return sorted(found, key=lambda v: [int(x) for x in re.findall(r'\d+', v)])


def install_ndk(sdk, version):
    """Скачать NDK напрямую из репозитория Google — без sdkmanager (новая обёртка «Android CLI» падает на Windows)."""
    import urllib.request
    import zipfile
    from xml.etree import ElementTree
    host = {'nt': 'windows'}.get(os.name, 'macosx' if sys.platform == 'darwin' else 'linux')
    with urllib.request.urlopen(REPOSITORY + 'repository2-3.xml', timeout=60) as response:
        root = ElementTree.fromstring(response.read())
    url = None
    for package in root.iter('remotePackage'):
        if package.get('path') != 'ndk;' + version:
            continue
        for archive in package.iter('archive'):
            if (archive.findtext('host-os') or host) == host:
                url = REPOSITORY + archive.find('complete').findtext('url')
    if not url:
        raise RuntimeError(f'NDK {version} для {host} не найден в репозитории Google')
    archive = sdk/'ndk'/f'ndk-{version}.zip.part'
    archive.parent.mkdir(parents=True, exist_ok=True)
    print(f'Скачиваю Android NDK {version} (≈700 МБ, один раз): {url}')
    with urllib.request.urlopen(url, timeout=60) as response, open(archive, 'wb') as out:
        total = int(response.headers.get('Content-Length') or 0)
        done, shown = 0, -1
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            percent = done * 100 // total if total else 0
            if percent != shown and percent % 5 == 0:
                print(f'  NDK: {percent}%', flush=True)
                shown = percent
    temp = sdk/'ndk'/f'.unpack-{version}'
    shutil.rmtree(temp, ignore_errors=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(temp)
    archive.unlink()
    inner = next(p for p in temp.iterdir() if p.is_dir())
    target = sdk/'ndk'/version
    shutil.rmtree(target, ignore_errors=True)
    inner.rename(target)
    shutil.rmtree(temp, ignore_errors=True)
    if sys.platform != 'win32':
        for item in target.rglob('*'):
            if item.is_file() and item.parent.name == 'bin':
                item.chmod(item.stat().st_mode | 0o755)
    return version


def ensure_ndk(flutter):
    """Вернуть версию NDK для build.gradle.kts так, чтобы Gradle не запускал sdkmanager."""
    sdk = sdk_dir()
    wanted = required_ndk(flutter)
    if sdk is None:
        print('WARNING: Android SDK not found; Gradle will try to install NDK itself.')
        return None
    have = installed_ndks(sdk)
    if wanted and wanted in have:
        return wanted
    if wanted:
        try:
            return install_ndk(sdk, wanted)
        except Exception as exc:
            print(f'WARNING: could not download NDK {wanted}: {exc}')
    if have:
        print(f'Using installed NDK {have[-1]}')
        return have[-1]
    raise RuntimeError('Не найден Android NDK. Установите его: Android Studio → Settings → Languages & Frameworks → '
                       'Android SDK → SDK Tools → «NDK (Side by side)» → Apply, затем повторите BUILD_ANDROID.bat.')


def app_version():
    """Версия для магазинов: имя — из app.py (5.4), номер сборки растёт с каждой сборкой (требование Play и RuStore)."""
    match = re.search(r"^VERSION = '([\d.]+)'", (ROOT/'app.py').read_text(encoding='utf-8'), re.M)
    name = match.group(1) if match else '1.0'
    if name.count('.') == 1:
        name += '.0'
    code = os.getenv('LOCAL_AI_ANDROID_BUILD_NUMBER') or str(int(time.time() // 60) - 29_000_000)
    return name, code


def main():
    targets = [a.lower() for a in sys.argv[1:]] or ['apk', 'aab']
    if not set(targets) <= {'apk', 'aab'}:
        raise SystemExit('Usage: BUILD_ANDROID.bat [apk] [aab]')
    flutter = tool('flutter')
    dart = Path(flutter).with_name('dart.bat' if os.name == 'nt' else 'dart')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # Generated build tree only; original android_client/lib and keys are never removed.
    if TARGET.exists():
        shutil.rmtree(TARGET)
    run([flutter, 'create', '--platforms=android', '--org=com.localaiagent', '--project-name=local_ai_agent', '--no-pub', TARGET])
    if (TARGET/'test').exists():
        shutil.rmtree(TARGET/'test')  # Generated counter-app test refers to MyApp, not AgentApp.
    for name in ('lib', 'assets', 'test'):
        shutil.copytree(ROOT/'android_client'/name, TARGET/name, dirs_exist_ok=True)
    shutil.copy2(ROOT/'android_client/pubspec.yaml', TARGET/'pubspec.yaml')
    lockfile = ROOT/'android_client/pubspec.lock'
    if lockfile.exists():
        shutil.copy2(lockfile, TARGET/'pubspec.lock')
    manifest = TARGET/'android/app/src/main/AndroidManifest.xml'
    text = manifest.read_text(encoding='utf-8')
    text = text.replace('<application', '<uses-permission android:name="android.permission.INTERNET"/>\n    <uses-permission android:name="android.permission.RECORD_AUDIO"/>\n    <application android:usesCleartextTraffic="true" android:allowBackup="false"', 1)
    text = text.replace('android:label="local_ai_agent"', 'android:label="Андрей"')
    manifest.write_text(text, encoding='utf-8')
    value = signing()
    props = TARGET/'android/key.properties'
    # Java Properties input is Latin-1; escape Cyrillic paths/passwords as Unicode sequences.
    props.write_text('\n'.join(k+'='+json.dumps(str(v), ensure_ascii=True)[1:-1] for k,v in value.items()), encoding='ascii')
    gradle = TARGET/'android/app/build.gradle.kts'
    if not gradle.exists():
        raise RuntimeError('This script requires current Flutter with Kotlin Gradle DSL. Update Flutter stable.')
    text = gradle.read_text(encoding='utf-8')
    header = 'import java.util.Properties\n\n'
    signing_block = '''android {
    val keyProperties = Properties().apply {
        rootProject.file("key.properties").inputStream().use { load(it) }
    }
    signingConfigs {
        create("release") {
            storeFile = file(keyProperties["storeFile"] as String)
            storePassword = keyProperties["storePassword"] as String
            keyAlias = keyProperties["keyAlias"] as String
            keyPassword = keyProperties["keyPassword"] as String
        }
    }
'''
    if 'signingConfigs.getByName("debug")' not in text:
        raise RuntimeError('Flutter signing template changed. Review .build/android/android/app/build.gradle.kts.')
    text = header+text.replace('android {', signing_block, 1)
    text = text.replace('signingConfigs.getByName("debug")', 'signingConfigs.getByName("release")')
    text = text.replace('minSdk = flutter.minSdkVersion', 'minSdk = maxOf(flutter.minSdkVersion, 23)')
    ndk = ensure_ndk(flutter)
    if ndk:
        # Готовый NDK: Gradle не будет вызывать sdkmanager (он падает с 0xC0000409 в новых cmdline-tools).
        text = text.replace('ndkVersion = flutter.ndkVersion', f'ndkVersion = "{ndk}"')
    gradle.write_text(text, encoding='utf-8')
    run([flutter, 'pub', 'get'], TARGET)
    run([dart if dart.exists() else flutter, *([] if dart.exists() else ['pub']), 'run', 'flutter_launcher_icons'], TARGET)
    run([flutter, 'analyze', '--no-fatal-infos'], TARGET)
    run([flutter, 'test'], TARGET)
    name, code = app_version()
    version = ['--build-name', name, '--build-number', code]
    output = ROOT/'release'
    output.mkdir(exist_ok=True)
    ready = []
    try:
        if 'apk' in targets:
            run([flutter, 'build', 'apk', '--release', *version], TARGET)
            shutil.copy2(TARGET/'build/app/outputs/flutter-apk/app-release.apk', output/'LocalAIAgent.apk')
            ready.append(output/'LocalAIAgent.apk')
        if 'aab' in targets:
            run([flutter, 'build', 'appbundle', '--release', *version], TARGET)
            shutil.copy2(TARGET/'build/app/outputs/bundle/release/app-release.aab', output/'LocalAIAgent.aab')
            ready.append(output/'LocalAIAgent.aab')
    finally:
        # Do not leave a second plaintext password file in the generated build tree.
        props.unlink(missing_ok=True)
    print(f'Version {name} (build {code})')
    for path in ready:
        print('Ready: '+str(path))


if __name__ == '__main__':
    main()
