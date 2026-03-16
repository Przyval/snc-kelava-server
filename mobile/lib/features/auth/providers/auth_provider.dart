import 'package:flutter/material.dart';
import '../../../core/models/user_model.dart';
import '../../../core/services/auth_service.dart';

enum AuthState { initial, loading, authenticated, unauthenticated, error }

class AuthProvider extends ChangeNotifier {
  final _service = AuthService();

  AuthState _state = AuthState.initial;
  UserModel? _user;
  String? _error;

  AuthState get state => _state;
  UserModel? get user => _user;
  String? get error => _error;
  bool get isAuthenticated => _state == AuthState.authenticated;

  Future<void> initialize() async {
    _state = AuthState.loading;
    notifyListeners();

    final user = await _service.getCachedUser();
    final loggedIn = await _service.isLoggedIn();

    if (loggedIn && user != null) {
      _user = user;
      _state = AuthState.authenticated;
    } else {
      _state = AuthState.unauthenticated;
    }
    notifyListeners();
  }

  Future<bool> login(String login, String password) async {
    _state = AuthState.loading;
    _error = null;
    notifyListeners();

    try {
      _user = await _service.login(login, password);
      _state = AuthState.authenticated;
      notifyListeners();
      return true;
    } catch (e) {
      _error = _parseError(e);
      _state = AuthState.error;
      notifyListeners();
      return false;
    }
  }

  Future<void> logout() async {
    await _service.logout();
    _user = null;
    _state = AuthState.unauthenticated;
    notifyListeners();
  }

  String _parseError(dynamic e) {
    try {
      final data = (e as dynamic).response?.data;
      if (data is Map) return data['error'] as String? ?? 'Login gagal';
    } catch (_) {}
    return 'Koneksi bermasalah. Cek internet anda.';
  }
}
