import 'package:flutter_test/flutter_test.dart';
import 'package:local_ai_agent/api.dart';

void main() {
  test('ссылка из QR-кода ПК', () {
    final pairing = Pairing.parse('http://192.168.1.5:8765/#token=abcDEF123_-abcDEF123_-xyz&device=iphone')!;
    expect(pairing.base.toString(), 'http://192.168.1.5:8765');
    expect(pairing.token, 'abcDEF123_-abcDEF123_-xyz');
    expect(pairing.hasRelay, isFalse);
    expect(Pairing.parse(pairing.link)!.token, pairing.token);
  });

  test('несколько адресов ПК и мост через интернет', () {
    final pairing = Pairing.parse('http://192.168.1.5:5000/#token=abcDEF123_-abcDEF123_-xyz&device=iphone'
        '&hosts=10.0.0.7,172.20.1.2&relay=https%3A%2F%2Fandrey.amvera.io&rid=AbCdEfGhIjKlMnOpQr')!;
    expect(pairing.bases.map((b) => b.host), ['192.168.1.5', '10.0.0.7', '172.20.1.2']);
    expect(pairing.bases.last.port, 5000);
    expect(pairing.relay.toString(), 'https://andrey.amvera.io');
    expect(pairing.rid, 'AbCdEfGhIjKlMnOpQr');
    final again = Pairing.parse(pairing.link)!;
    expect(again.bases.length, 3);
    expect(again.hasRelay, isTrue);
    // Тот же ключ, что считает ПК (src/relay_client.py: HMAC-SHA256(token, "andrey-relay")).
    expect(pairing.relayKey, 'e58d19481a1b4c71577b07f6c302f0451b50d931125c2c413b7b8c3817e8d7d7');
  });

  test('мост только по https', () {
    final pairing = Pairing.parse('http://192.168.1.5:5000/#token=abcDEF123_-abcDEF123_-xyz'
        '&relay=http%3A%2F%2Fevil.example&rid=AbCdEfGhIjKlMnOpQr')!;
    expect(pairing.hasRelay, isFalse);
  });

  test('чужие ссылки не принимаются', () {
    expect(Pairing.parse('https://example.com/'), isNull);
    expect(Pairing.parse('ftp://1.2.3.4/#token=abcDEF123_-abcDEF123_-xyz'), isNull);
    expect(Pairing.parse('просто текст'), isNull);
  });

  test('идентификаторы подходят серверу', () {
    expect(RegExp(r'^[a-zA-Z0-9_-]{1,80}$').hasMatch(AgentApi.newDeviceId()), isTrue);
    expect(RegExp(r'^[a-zA-Z0-9_-]{8,100}$').hasMatch(AgentApi.newCommandId()), isTrue);
  });
}
