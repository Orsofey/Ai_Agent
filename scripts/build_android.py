"""Generate Android platform files with installed Flutter; keep a stable signing key."""
import json
import os
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


def main():
    flutter = tool('flutter')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # Generated build tree only; original android_client/lib and keys are never removed.
    if TARGET.exists():
        shutil.rmtree(TARGET)
    run([flutter, 'create', '--platforms=android', '--org=com.localaiagent', '--project-name=local_ai_agent', '--no-pub', TARGET])
    for name in ('lib', 'assets'):
        shutil.copytree(ROOT/'android_client'/name, TARGET/name, dirs_exist_ok=True)
    shutil.copy2(ROOT/'android_client/pubspec.yaml', TARGET/'pubspec.yaml')
    lockfile = ROOT/'android_client/pubspec.lock'
    if lockfile.exists():
        shutil.copy2(lockfile, TARGET/'pubspec.lock')
    if (TARGET/'test').exists():
        shutil.rmtree(TARGET/'test')  # Generated counter-app test refers to MyApp, not AgentApp.
    manifest = TARGET/'android/app/src/main/AndroidManifest.xml'
    text = manifest.read_text()
    text = text.replace('<application', '<uses-permission android:name="android.permission.INTERNET"/>\n    <uses-permission android:name="android.permission.RECORD_AUDIO"/>\n    <application android:usesCleartextTraffic="true" android:allowBackup="false"', 1)
    text = text.replace('android:label="local_ai_agent"', 'android:label="Local AI Agent"')
    manifest.write_text(text, encoding='utf-8')
    value = signing()
    props = TARGET/'android/key.properties'
    # Java Properties input is Latin-1; escape Cyrillic paths/passwords as Unicode sequences.
    props.write_text('\n'.join(k+'='+json.dumps(str(v), ensure_ascii=True)[1:-1] for k,v in value.items()), encoding='ascii')
    gradle = TARGET/'android/app/build.gradle.kts'
    if not gradle.exists():
        raise RuntimeError('This script requires current Flutter with Kotlin Gradle DSL. Update Flutter stable.')
    text = gradle.read_text()
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
    gradle.write_text(text, encoding='utf-8')
    run([flutter, 'pub', 'get'], TARGET)
    run([flutter, 'pub', 'run', 'flutter_launcher_icons'], TARGET)
    run([flutter, 'analyze', '--no-fatal-infos'], TARGET)
    run([flutter, 'build', 'apk', '--release'], TARGET)
    output = ROOT/'release'
    output.mkdir(exist_ok=True)
    shutil.copy2(TARGET/'build/app/outputs/flutter-apk/app-release.apk', output/'LocalAIAgent.apk')
    # Do not leave a second plaintext password file in the generated build tree.
    props.unlink(missing_ok=True)
    print('Ready: '+str(output/'LocalAIAgent.apk'))


if __name__ == '__main__':
    main()
