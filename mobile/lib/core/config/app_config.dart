class AppConfig {
  static const String baseUrl = 'https://safencare.work/api/v1';
  static const String appName = 'SNC';
  static const String appVersion = '1.0.0';

  // Endpoint paths
  static const String loginPath = '/auth/login';
  static const String refreshPath = '/auth/refresh';
  static const String mePath = '/auth/me';
  static const String logoutPath = '/auth/logout';

  static const String mobileDashboardPath = '/mobile/dashboard';
  static const String mobileVisitsPath = '/mobile/visits';
  static const String mobileCustomersPath = '/mobile/customers';
  static const String mobileApprovalsPath = '/mobile/approvals';

  // Scheduling write (Fase 2)
  static const String roadPlansPath = '/enterprise/scheduling/road-plans';
  static const String fcmTokenPath = '/enterprise/scheduling/fcm-token';
}
