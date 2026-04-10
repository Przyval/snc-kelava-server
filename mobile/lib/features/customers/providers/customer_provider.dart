import 'package:flutter/material.dart';
import '../../../core/config/app_config.dart';
import '../../../core/models/customer_model.dart';
import '../../../core/models/contract_model.dart';
import '../../../core/services/api_service.dart';

class CustomerProvider extends ChangeNotifier {
  final _api = ApiService();

  List<CustomerModel> _all = [];
  List<CustomerModel> _filtered = [];
  bool _loading = false;
  String? _error;
  String _query = '';
  bool _saving = false;

  List<CustomerModel> get customers => _filtered;
  bool get loading => _loading;
  bool get saving => _saving;
  String? get error => _error;

  Future<void> load({String source = 'all'}) async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final res = await _api.get(
        '${AppConfig.baseUrl}/enterprise/customers/all?source=$source&limit=500',
      );
      _all = (res.data['customers'] as List? ?? [])
          .map((e) => CustomerModel.fromJson(e as Map<String, dynamic>))
          .toList();
      _applyFilter();
    } catch (e) {
      // Fallback: try legacy path
      try {
        final res = await _api.get(AppConfig.mobileCustomersPath);
        _all = (res.data as List? ?? [])
            .map((e) => CustomerModel.fromJson(e as Map<String, dynamic>))
            .toList();
        _applyFilter();
      } catch (_) {
        _error = 'Gagal memuat pelanggan';
      }
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  void search(String query) {
    _query = query.toLowerCase();
    _applyFilter();
    notifyListeners();
  }

  void _applyFilter() {
    if (_query.isEmpty) {
      _filtered = List.from(_all);
    } else {
      _filtered = _all.where((c) {
        return c.name.toLowerCase().contains(_query) ||
            c.code.toLowerCase().contains(_query) ||
            (c.address?.toLowerCase().contains(_query) ?? false) ||
            (c.city?.toLowerCase().contains(_query) ?? false);
      }).toList();
    }
  }

  // ── Create customer ───────────────────────────────────────────────────────

  Future<bool> createCustomer(Map<String, dynamic> data) async {
    _saving = true;
    _error = null;
    notifyListeners();

    try {
      await _api.post('${AppConfig.baseUrl}/enterprise/customers/create', data);
      await load();
      return true;
    } catch (e) {
      _error = 'Gagal membuat pelanggan';
      return false;
    } finally {
      _saving = false;
      notifyListeners();
    }
  }

  // ── Contracts for a customer ──────────────────────────────────────────────

  Future<List<ContractModel>> loadContracts({
    int? kelavaCustomerId,
    int? sncCustomerId,
    bool activeOnly = false,
  }) async {
    try {
      final params = <String>[];
      if (kelavaCustomerId != null) params.add('customer_id=$kelavaCustomerId');
      if (sncCustomerId != null) params.add('snc_customer_id=$sncCustomerId');
      if (activeOnly) params.add('active_only=true');
      final query = params.isNotEmpty ? '?${params.join('&')}' : '';
      final res = await _api.get(
          '${AppConfig.baseUrl}/enterprise/contracts/all$query');
      return (res.data['contracts'] as List? ?? [])
          .map((e) => ContractModel.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (_) {
      return [];
    }
  }

  Future<List<ContractModel>> loadExpiringContracts(int days) async {
    try {
      final res = await _api.get(
          '${AppConfig.baseUrl}/enterprise/contracts/all?expiring_days=$days&active_only=true');
      return (res.data['contracts'] as List? ?? [])
          .map((e) => ContractModel.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (_) {
      return [];
    }
  }

  Future<bool> createContract(Map<String, dynamic> data) async {
    _saving = true;
    _error = null;
    notifyListeners();
    try {
      await _api.post('${AppConfig.baseUrl}/enterprise/contracts/create', data);
      return true;
    } catch (e) {
      _error = 'Gagal membuat kontrak';
      return false;
    } finally {
      _saving = false;
      notifyListeners();
    }
  }

  Future<bool> renewContract(int contractId, Map<String, dynamic> data) async {
    _saving = true;
    notifyListeners();
    try {
      await _api.post(
          '${AppConfig.baseUrl}/enterprise/contracts/snc/$contractId/renew',
          data);
      return true;
    } catch (_) {
      _error = 'Gagal memperbarui kontrak';
      return false;
    } finally {
      _saving = false;
      notifyListeners();
    }
  }
}
