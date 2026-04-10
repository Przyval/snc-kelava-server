import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../providers/scheduling_provider.dart';
import '../../../core/services/api_service.dart';
import '../../../core/config/app_config.dart';
import '../../../core/theme/app_theme.dart';

class CreateRoadPlanScreen extends StatefulWidget {
  const CreateRoadPlanScreen({super.key});

  @override
  State<CreateRoadPlanScreen> createState() => _CreateRoadPlanScreenState();
}

class _CreateRoadPlanScreenState extends State<CreateRoadPlanScreen> {
  final _formKey = GlobalKey<FormState>();
  final _titleCtrl = TextEditingController();
  final _remarksCtrl = TextEditingController();

  DateTime _visitDate = DateTime.now().add(const Duration(days: 1));
  TimeOfDay _visitTime = const TimeOfDay(hour: 9, minute: 0);

  // Selected technician
  int? _selectedUserId;
  String? _selectedUserName;

  // Selected customer
  int? _selectedCustomerId;
  String? _selectedCustomerName;
  int? _selectedKontrakId;
  String? _selectedKontrakNo;

  // Dropdown data
  List<Map<String, dynamic>> _technicians = [];
  List<Map<String, dynamic>> _customers = [];
  List<Map<String, dynamic>> _contracts = [];

  bool _loadingData = true;
  final _api = ApiService();

  @override
  void initState() {
    super.initState();
    _loadFormData();
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    _remarksCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadFormData() async {
    try {
      final [techRes, custRes] = await Future.wait([
        _api.get('${AppConfig.baseUrl}/enterprise/technicians/leaderboard?limit=100'),
        _api.get('${AppConfig.baseUrl}/enterprise/customers?limit=500'),
      ]);

      setState(() {
        _technicians = (techRes.data['leaderboard'] as List? ?? [])
            .map((e) => {
                  'id': e['technician_id'] ?? e['id'],
                  'name': e['technician_name'] ?? e['fullname'] ?? '-',
                })
            .toList();
        _customers = (custRes.data['customers'] as List? ??
                custRes.data as List? ??
                [])
            .map((e) => {
                  'id': e['id'],
                  'name': e['name'] ?? '-',
                  'address': e['address'],
                })
            .toList();
        _loadingData = false;
      });
    } catch (_) {
      setState(() => _loadingData = false);
    }
  }

  Future<void> _loadContracts(int customerId) async {
    try {
      final res = await _api.get(
          '${AppConfig.baseUrl}/enterprise/contracts?customer_id=$customerId');
      final list = res.data['contracts'] as List? ?? [];
      setState(() {
        _contracts = list
            .map((e) => {
                  'id': e['id'],
                  'no_kontrak': e['no_kontrak'] ?? '-',
                  'is_active': e['is_active'],
                })
            .toList();
      });
    } catch (_) {
      setState(() => _contracts = []);
    }
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _visitDate,
      firstDate: DateTime.now(),
      lastDate: DateTime.now().add(const Duration(days: 180)),
      locale: const Locale('id'),
    );
    if (picked != null) setState(() => _visitDate = picked);
  }

  Future<void> _pickTime() async {
    final picked = await showTimePicker(
      context: context,
      initialTime: _visitTime,
    );
    if (picked != null) setState(() => _visitTime = picked);
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedUserId == null || _selectedCustomerId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Pilih teknisi dan pelanggan terlebih dahulu')),
      );
      return;
    }

    final visitDateTime = DateTime(
      _visitDate.year,
      _visitDate.month,
      _visitDate.day,
      _visitTime.hour,
      _visitTime.minute,
    );

    final ok = await context.read<SchedulingProvider>().createRoadPlan(
          pUserId: _selectedUserId!,
          customerId: _selectedCustomerId!,
          visitDate: visitDateTime,
          kontrakId: _selectedKontrakId,
          title: _titleCtrl.text.trim(),
          remarks: _remarksCtrl.text.trim(),
        );

    if (ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Jadwal berhasil dibuat!'),
          backgroundColor: Colors.green,
        ),
      );
      Navigator.pop(context, true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sched = context.watch<SchedulingProvider>();
    final dateFmt = DateFormat('EEEE, d MMM yyyy', 'id');

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: const Text('Buat Jadwal Kunjungan'),
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: _loadingData
          ? const Center(child: CircularProgressIndicator())
          : Form(
              key: _formKey,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  // Date & Time
                  _SectionHeader(title: 'Waktu Kunjungan'),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: _PickerCard(
                          label: 'Tanggal',
                          value: dateFmt.format(_visitDate),
                          icon: Icons.calendar_today,
                          onTap: _pickDate,
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: _PickerCard(
                          label: 'Jam',
                          value: _visitTime.format(context),
                          icon: Icons.access_time,
                          onTap: _pickTime,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),

                  // Technician
                  _SectionHeader(title: 'Teknisi'),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<int>(
                    decoration: _inputDecoration('Pilih Teknisi'),
                    value: _selectedUserId,
                    isExpanded: true,
                    items: _technicians
                        .map((t) => DropdownMenuItem<int>(
                              value: t['id'] as int,
                              child: Text(t['name'] as String,
                                  overflow: TextOverflow.ellipsis),
                            ))
                        .toList(),
                    onChanged: (v) => setState(() {
                      _selectedUserId = v;
                      _selectedUserName = _technicians
                          .firstWhere((t) => t['id'] == v)['name'] as String?;
                    }),
                    validator: (v) => v == null ? 'Pilih teknisi' : null,
                  ),
                  const SizedBox(height: 20),

                  // Customer
                  _SectionHeader(title: 'Pelanggan'),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<int>(
                    decoration: _inputDecoration('Pilih Pelanggan'),
                    value: _selectedCustomerId,
                    isExpanded: true,
                    items: _customers
                        .map((c) => DropdownMenuItem<int>(
                              value: c['id'] as int,
                              child: Text(c['name'] as String,
                                  overflow: TextOverflow.ellipsis),
                            ))
                        .toList(),
                    onChanged: (v) {
                      setState(() {
                        _selectedCustomerId = v;
                        _selectedKontrakId = null;
                        _selectedKontrakNo = null;
                        _contracts = [];
                      });
                      if (v != null) _loadContracts(v);
                    },
                    validator: (v) => v == null ? 'Pilih pelanggan' : null,
                  ),
                  if (_contracts.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    DropdownButtonFormField<int>(
                      decoration: _inputDecoration('Kontrak (opsional)'),
                      value: _selectedKontrakId,
                      isExpanded: true,
                      items: [
                        const DropdownMenuItem<int>(
                            value: null, child: Text('— Tanpa kontrak —')),
                        ..._contracts.map((k) => DropdownMenuItem<int>(
                              value: k['id'] as int,
                              child: Text(k['no_kontrak'] as String),
                            )),
                      ],
                      onChanged: (v) => setState(() {
                        _selectedKontrakId = v;
                        _selectedKontrakNo = v != null
                            ? _contracts.firstWhere(
                                (k) => k['id'] == v)['no_kontrak'] as String?
                            : null;
                      }),
                    ),
                  ],
                  const SizedBox(height: 20),

                  // Optional fields
                  _SectionHeader(title: 'Keterangan (Opsional)'),
                  const SizedBox(height: 8),
                  TextFormField(
                    controller: _titleCtrl,
                    decoration: _inputDecoration('Judul / catatan singkat'),
                  ),
                  const SizedBox(height: 10),
                  TextFormField(
                    controller: _remarksCtrl,
                    decoration: _inputDecoration('Instruksi khusus untuk teknisi'),
                    maxLines: 3,
                  ),
                  const SizedBox(height: 32),

                  // Error
                  if (sched.error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(sched.error!,
                          style: const TextStyle(color: Colors.red),
                          textAlign: TextAlign.center),
                    ),

                  // Submit
                  ElevatedButton(
                    onPressed: sched.saving ? null : _submit,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.primary,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                    ),
                    child: sched.saving
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(
                                color: Colors.white, strokeWidth: 2))
                        : const Text('Buat Jadwal',
                            style: TextStyle(
                                fontSize: 16, fontWeight: FontWeight.w700)),
                  ),
                  const SizedBox(height: 32),
                ],
              ),
            ),
    );
  }

  InputDecoration _inputDecoration(String label) => InputDecoration(
        labelText: label,
        filled: true,
        fillColor: Colors.white,
        border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: BorderSide(color: Colors.grey.shade300)),
        enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: BorderSide(color: Colors.grey.shade300)),
        focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: AppColors.primary)),
      );
}

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader({required this.title});

  @override
  Widget build(BuildContext context) => Text(title,
      style: const TextStyle(
          fontWeight: FontWeight.w700,
          fontSize: 13,
          color: AppColors.textSecondary,
          letterSpacing: 0.5));
}

class _PickerCard extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;
  final VoidCallback onTap;

  const _PickerCard({
    required this.label,
    required this.value,
    required this.icon,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: Colors.grey.shade300),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label,
                style: TextStyle(
                    fontSize: 11,
                    color: Colors.grey.shade500,
                    fontWeight: FontWeight.w500)),
            const SizedBox(height: 4),
            Row(
              children: [
                Icon(icon, size: 14, color: AppColors.primary),
                const SizedBox(width: 6),
                Expanded(
                    child: Text(value,
                        style: const TextStyle(
                            fontWeight: FontWeight.w600, fontSize: 12))),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
