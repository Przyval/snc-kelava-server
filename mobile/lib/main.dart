import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'core/services/notification_service.dart';
import 'core/theme/app_theme.dart';
import 'features/auth/providers/auth_provider.dart';
import 'features/auth/screens/login_screen.dart';
import 'features/dashboard/providers/dashboard_provider.dart';
import 'features/visits/providers/visit_provider.dart';
import 'features/customers/providers/customer_provider.dart';
import 'features/approvals/providers/approvals_provider.dart';
import 'features/scheduling/providers/scheduling_provider.dart';
import 'features/home/home_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('id', null);

  // Firebase + Push Notifications
  // Note: requires google-services.json (Android) and GoogleService-Info.plist (iOS)
  // to be added before building. Gracefully skip if not configured yet.
  try {
    await Firebase.initializeApp();
    await NotificationService.instance.init();
  } catch (_) {
    // Firebase not configured yet — skip, app works without it
  }

  runApp(const SNCApp());
}

class SNCApp extends StatelessWidget {
  const SNCApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthProvider()),
        ChangeNotifierProvider(create: (_) => DashboardProvider()),
        ChangeNotifierProvider(create: (_) => VisitProvider()),
        ChangeNotifierProvider(create: (_) => CustomerProvider()),
        ChangeNotifierProvider(create: (_) => ApprovalsProvider()),
        ChangeNotifierProvider(create: (_) => SchedulingProvider()),
      ],
      child: MaterialApp(
        title: 'SNC',
        theme: AppTheme.theme,
        debugShowCheckedModeBanner: false,
        home: const _AppRoot(),
      ),
    );
  }
}

class _AppRoot extends StatefulWidget {
  const _AppRoot();

  @override
  State<_AppRoot> createState() => _AppRootState();
}

class _AppRootState extends State<_AppRoot> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<AuthProvider>().initialize();
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();

    switch (auth.state) {
      case AuthState.initial:
      case AuthState.loading:
        return const Scaffold(
          body: Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                CircularProgressIndicator(),
                SizedBox(height: 16),
                Text(
                  'SNC',
                  style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 3,
                    color: AppColors.primary,
                  ),
                ),
              ],
            ),
          ),
        );
      case AuthState.authenticated:
        return const HomeScreen();
      default:
        return const LoginScreen();
    }
  }
}
