import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/customer_provider.dart';
import '../../../core/theme/app_theme.dart';

class CreateCustomerScreen extends StatefulWidget {
  const CreateCustomerScreen({super.key});

  @override
  State<CreateCustomerScreen> createState() => _CreateCustomerScreenState();
}

class _CreateCustomerScreenState extends State<CreateCustomerScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _addressCtrl = TextEditingController();
  final _cityCtrl = TextEditingController();
  final _provinceCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _cpNameCtrl = TextEditingController();
  final _cpPhoneCtrl = TextEditingController();

  String? _segment;
  String _status = 'Active';

  static const _segments = ['Mobile', 'Station', 'Industrial', 'Residential'];
  static const _statuses = ['Active', 'Inactive'];

  @override
  void dispose() {
    _nameCtrl.dispose();
    _addressCtrl.dispose();
    _cityCtrl.dispose();
    _provinceCtrl.dispose();
    _phoneCtrl.dispose();
    _emailCtrl.dispose();
    _cpNameCtrl.dispose();
    _cpPhoneCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    final data = {
      'name': _nameCtrl.text.trim(),
      'address': _addressCtrl.text.trim().isEmpty ? null : _addressCtrl.text.trim(),
      'new_city': _cityCtrl.text.trim().isEmpty ? null : _cityCtrl.text.trim(),
      'new_province':
          _provinceCtrl.text.trim().isEmpty ? null : _provinceCtrl.text.trim(),
      'phone1': _phoneCtrl.text.trim().isEmpty ? null : _phoneCtrl.text.trim(),
      'email': _emailCtrl.text.trim().isEmpty ? null : _emailCtrl.text.trim(),
      'contact_person_name':
          _cpNameCtrl.text.trim().isEmpty ? null : _cpNameCtrl.text.trim(),
      'contact_person_phone':
          _cpPhoneCtrl.text.trim().isEmpty ? null : _cpPhoneCtrl.text.trim(),
      'segment': _segment,
      'status': _status,
    };

    final ok = await context.read<CustomerProvider>().createCustomer(data);
    if (ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Pelanggan berhasil ditambahkan!'),
          backgroundColor: Colors.green,
        ),
      );
      Navigator.pop(context, true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final prov = context.watch<CustomerProvider>();

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: const Text('Tambah Pelanggan'),
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _SectionHeader(title: 'Identitas Pelanggan'),
            const SizedBox(height: 8),
            _field(
              controller: _nameCtrl,
              label: 'Nama Pelanggan *',
              validator: (v) =>
                  v == null || v.trim().isEmpty ? 'Nama wajib diisi' : null,
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: DropdownButtonFormField<String>(
                    decoration: _dec('Segmen'),
                    value: _segment,
                    items: _segments
                        .map((s) =>
                            DropdownMenuItem(value: s, child: Text(s)))
                        .toList(),
                    onChanged: (v) => setState(() => _segment = v),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: DropdownButtonFormField<String>(
                    decoration: _dec('Status'),
                    value: _status,
                    items: _statuses
                        .map((s) =>
                            DropdownMenuItem(value: s, child: Text(s)))
                        .toList(),
                    onChanged: (v) => setState(() => _status = v ?? 'Active'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),

            _SectionHeader(title: 'Alamat'),
            const SizedBox(height: 8),
            _field(controller: _addressCtrl, label: 'Alamat', maxLines: 2),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                    child: _field(controller: _cityCtrl, label: 'Kota')),
                const SizedBox(width: 12),
                Expanded(
                    child: _field(
                        controller: _provinceCtrl, label: 'Provinsi')),
              ],
            ),
            const SizedBox(height: 20),

            _SectionHeader(title: 'Kontak'),
            const SizedBox(height: 8),
            _field(controller: _phoneCtrl, label: 'No. Telepon'),
            const SizedBox(height: 12),
            _field(
              controller: _emailCtrl,
              label: 'Email',
              keyboardType: TextInputType.emailAddress,
            ),
            const SizedBox(height: 20),

            _SectionHeader(title: 'Contact Person'),
            const SizedBox(height: 8),
            _field(
                controller: _cpNameCtrl, label: 'Nama Contact Person'),
            const SizedBox(height: 12),
            _field(
                controller: _cpPhoneCtrl,
                label: 'No. HP Contact Person'),
            const SizedBox(height: 32),

            if (prov.error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(prov.error!,
                    style: const TextStyle(color: Colors.red),
                    textAlign: TextAlign.center),
              ),

            ElevatedButton(
              onPressed: prov.saving ? null : _submit,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primary,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12)),
              ),
              child: prov.saving
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(
                          color: Colors.white, strokeWidth: 2))
                  : const Text('Simpan Pelanggan',
                      style: TextStyle(
                          fontSize: 16, fontWeight: FontWeight.w700)),
            ),
            const SizedBox(height: 32),
          ],
        ),
      ),
    );
  }

  Widget _field({
    required TextEditingController controller,
    required String label,
    String? Function(String?)? validator,
    TextInputType? keyboardType,
    int maxLines = 1,
  }) =>
      TextFormField(
        controller: controller,
        decoration: _dec(label),
        validator: validator,
        keyboardType: keyboardType,
        maxLines: maxLines,
      );

  InputDecoration _dec(String label) => InputDecoration(
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
