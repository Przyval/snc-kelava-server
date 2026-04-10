import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/models/customer_model.dart';
import '../../../core/theme/app_theme.dart';
import '../providers/customer_provider.dart';

/// Used for both creating a new contract and renewing an existing SNC contract.
class CreateContractScreen extends StatefulWidget {
  final CustomerModel customer;
  final int? renewContractId; // null = new contract, non-null = renewal

  const CreateContractScreen({
    super.key,
    required this.customer,
    this.renewContractId,
  });

  @override
  State<CreateContractScreen> createState() => _CreateContractScreenState();
}

class _CreateContractScreenState extends State<CreateContractScreen> {
  final _formKey = GlobalKey<FormState>();
  final _noKontrakCtrl = TextEditingController();
  final _nilaiCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();

  DateTime _startDate = DateTime.now();
  DateTime _endDate = DateTime.now().add(const Duration(days: 365));
  int _frekuensiVisit = 1;

  bool get _isRenewal => widget.renewContractId != null;

  @override
  void dispose() {
    _noKontrakCtrl.dispose();
    _nilaiCtrl.dispose();
    _notesCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickDate(bool isStart) async {
    final init = isStart ? _startDate : _endDate;
    final first = isStart ? DateTime.now() : _startDate;
    final picked = await showDatePicker(
      context: context,
      initialDate: init,
      firstDate: first,
      lastDate: DateTime.now().add(const Duration(days: 365 * 5)),
      locale: const Locale('id'),
    );
    if (picked != null) {
      setState(() {
        if (isStart) {
          _startDate = picked;
          if (_endDate.isBefore(picked)) {
            _endDate = picked.add(const Duration(days: 365));
          }
        } else {
          _endDate = picked;
        }
      });
    }
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    final prov = context.read<CustomerProvider>();
    final dateFmt = DateFormat('yyyy-MM-dd');
    bool ok;

    if (_isRenewal) {
      ok = await prov.renewContract(widget.renewContractId!, {
        'new_start_date': dateFmt.format(_startDate),
        'new_end_date': dateFmt.format(_endDate),
        if (_nilaiCtrl.text.trim().isNotEmpty)
          'nilai_kontrak': double.tryParse(
              _nilaiCtrl.text.trim().replaceAll('.', '').replaceAll(',', '.')),
      });
    } else {
      final cust = widget.customer;
      ok = await prov.createContract({
        'no_kontrak': _noKontrakCtrl.text.trim(),
        'start_date': dateFmt.format(_startDate),
        'end_date': dateFmt.format(_endDate),
        if (cust.isSNC) 'snc_customer_id': cust.id,
        if (!cust.isSNC) 'kelava_customer_id': cust.id,
        if (_nilaiCtrl.text.trim().isNotEmpty)
          'nilai_kontrak': double.tryParse(
              _nilaiCtrl.text.trim().replaceAll('.', '').replaceAll(',', '.')),
        'frekuensi_visit': _frekuensiVisit,
        if (_notesCtrl.text.trim().isNotEmpty) 'notes': _notesCtrl.text.trim(),
      });
    }

    if (ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(_isRenewal
              ? 'Kontrak berhasil diperpanjang!'
              : 'Kontrak berhasil dibuat!'),
          backgroundColor: Colors.green,
        ),
      );
      Navigator.pop(context, true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final prov = context.watch<CustomerProvider>();
    final dateFmt = DateFormat('d MMM yyyy', 'id');

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: Text(_isRenewal ? 'Perpanjang Kontrak' : 'Buat Kontrak'),
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Customer info
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppColors.primary.withOpacity(0.07),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Row(
                children: [
                  const Icon(Icons.business, color: AppColors.primary, size: 18),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(widget.customer.name,
                        style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            color: AppColors.primary)),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),

            _SectionHeader(title: 'Detail Kontrak'),
            const SizedBox(height: 8),

            if (!_isRenewal) ...[
              TextFormField(
                controller: _noKontrakCtrl,
                decoration: _dec('No. Kontrak *'),
                validator: (v) =>
                    v == null || v.trim().isEmpty ? 'No. kontrak wajib diisi' : null,
              ),
              const SizedBox(height: 12),
            ],

            // Date pickers
            Row(
              children: [
                Expanded(
                  child: _DatePicker(
                    label: 'Mulai',
                    value: dateFmt.format(_startDate),
                    onTap: () => _pickDate(true),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _DatePicker(
                    label: 'Berakhir',
                    value: dateFmt.format(_endDate),
                    onTap: () => _pickDate(false),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),

            TextFormField(
              controller: _nilaiCtrl,
              decoration: _dec('Nilai Kontrak (Rp)'),
              keyboardType: TextInputType.number,
            ),

            if (!_isRenewal) ...[
              const SizedBox(height: 12),
              Row(
                children: [
                  const Text('Frekuensi Visit / bulan:',
                      style: TextStyle(
                          fontSize: 13, color: AppColors.textSecondary)),
                  const SizedBox(width: 12),
                  _CounterButton(
                    value: _frekuensiVisit,
                    onDecrement: () =>
                        setState(() => _frekuensiVisit = (_frekuensiVisit - 1).clamp(1, 12)),
                    onIncrement: () =>
                        setState(() => _frekuensiVisit = (_frekuensiVisit + 1).clamp(1, 12)),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _notesCtrl,
                decoration: _dec('Catatan'),
                maxLines: 3,
              ),
            ],

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
                  : Text(
                      _isRenewal ? 'Perpanjang Kontrak' : 'Simpan Kontrak',
                      style: const TextStyle(
                          fontSize: 16, fontWeight: FontWeight.w700)),
            ),
            const SizedBox(height: 32),
          ],
        ),
      ),
    );
  }

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

class _DatePicker extends StatelessWidget {
  final String label;
  final String value;
  final VoidCallback onTap;
  const _DatePicker(
      {required this.label, required this.value, required this.onTap});

  @override
  Widget build(BuildContext context) => GestureDetector(
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
                  const Icon(Icons.calendar_today,
                      size: 13, color: AppColors.primary),
                  const SizedBox(width: 6),
                  Text(value,
                      style: const TextStyle(
                          fontWeight: FontWeight.w600, fontSize: 12)),
                ],
              ),
            ],
          ),
        ),
      );
}

class _CounterButton extends StatelessWidget {
  final int value;
  final VoidCallback onDecrement;
  final VoidCallback onIncrement;
  const _CounterButton(
      {required this.value,
      required this.onDecrement,
      required this.onIncrement});

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            icon: const Icon(Icons.remove_circle_outline),
            onPressed: value > 1 ? onDecrement : null,
            color: AppColors.primary,
            iconSize: 20,
          ),
          Text('$value',
              style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 16,
                  color: AppColors.textPrimary)),
          IconButton(
            icon: const Icon(Icons.add_circle_outline),
            onPressed: value < 12 ? onIncrement : null,
            color: AppColors.primary,
            iconSize: 20,
          ),
        ],
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
