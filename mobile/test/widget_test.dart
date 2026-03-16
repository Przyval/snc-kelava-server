import 'package:flutter_test/flutter_test.dart';
import 'package:snc/main.dart';

void main() {
  testWidgets('SNC app smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const SNCApp());
    expect(find.byType(SNCApp), findsOneWidget);
  });
}
