import 'package:flutter_test/flutter_test.dart';
import 'package:local_ai_agent/api.dart';

void main() {
  test('ссылка из QR-кода ПК', () {
    final pairing = Pairing.parse('http://192.168.1.5:8765/#token=abcDEF123_-abcDEF123_-xyz&device=iphone')!;
    expect(pairing.base.toString(), 'http://192.168.1.5:8765');
    expect(pairing.token, 'abcDEF123_-abcDEF123_-xyz');
    expect(Pairing.parse(pairing.link)!.token, pairing.token);
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
