import 'dart:convert';
import '../config/app_config.dart';
import '../models/user_model.dart';
import 'api_service.dart';
import 'storage_service.dart';

class AuthService {
  static final AuthService _instance = AuthService._();
  factory AuthService() => _instance;
  AuthService._();

  final _api = ApiService();

  Future<UserModel> login(String login, String password) async {
    final res = await _api.post(
      AppConfig.loginPath,
      data: {'login': login, 'password': password},
    );
    final data = res.data as Map<String, dynamic>;
    await StorageService.saveTokens(
      accessToken: data['access_token'] as String,
      refreshToken: data['refresh_token'] as String,
    );
    final user = UserModel.fromJson(data['user'] as Map<String, dynamic>);
    await StorageService.saveUserJson(jsonEncode(data['user']));
    return user;
  }

  Future<void> logout() async {
    try {
      final refresh = await StorageService.getRefreshToken();
      if (refresh != null) {
        await _api.post(AppConfig.logoutPath, data: {'refresh_token': refresh});
      }
    } catch (_) {}
    await StorageService.clearAll();
  }

  Future<UserModel?> getCachedUser() async {
    final json = await StorageService.getUserJson();
    if (json == null) return null;
    try {
      return UserModel.fromJson(jsonDecode(json) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  Future<bool> isLoggedIn() async {
    final token = await StorageService.getAccessToken();
    return token != null;
  }
}
