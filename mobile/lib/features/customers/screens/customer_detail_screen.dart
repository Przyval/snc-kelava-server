import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/models/customer_model.dart';
import '../../../core/models/contract_model.dart';
import '../../../core/theme/app_theme.dart';
import '../providers/customer_provider.dart';
import '../../auth/providers/auth_provider.dart';
import 'create_contract_screen.dart';

class CustomerDetailScreen extends StatefulWidget {
  final CustomerModel customer;
  const CustomerDetailScreen({super.key, required this.customer});

  @override
  State<CustomerDetailScreen> createState() => _CustomerDetailScreenState();
}

class _CustomerDetailScreenState extends State<CustomerDetailScreen> {
  List<ContractModel> _contracts = [];
  bool _loadingContracts = true;

  @override
  void initState() {
    super.initState();
    _loadContracts();
  }

  Future<void> _loadContracts() async {
    final prov = context.read<CustomerProvider>();
    final list = await prov.loadContracts(
      kelavaCustomerId: widget.customer.isSNC ? null : widget.customer.id,
      sncCustomerId: widget.customer.isSNC ? widget.customer.id : null,
    );
    if (mounted) setState(() {
      _contracts = list;
      _loadingContracts = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.customer;
    final user = context.watch<AuthProvider>().user;
    final canEdit = user?.isSupervisor ?? false;

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: const Text('Detail Pelanggan'),
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      floatingActionButton: canEdit
          ? FloatingActionButton.extended(
              onPressed: () async {
                final ok = await Navigator.push<bool>(
                  context,
                  MaterialPageRoute(
                      builder: (_) => CreateContractScreen(customer: c)),
                );
                if (ok == true) _loadContracts();
              },
              backgroundColor: AppColors.primary,
              foregroundColor: Colors.white,
              icon: const Icon(Icons.add),
              label: const Text('Buat Kontrak'),
            )
          : null,
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Header card
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(14),
              boxShadow: const [
                BoxShadow(color: AppColors.cardShadow, blurRadius: 6)
              ],
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    CircleAvatar(
                      radius: 26,
                      backgroundColor: AppColors.primary.withOpacity(0.12),
                      child: Text(c.initials,
                          style: const TextStyle(
                              color: AppColors.primary,
                              fontWeight: FontWeight.bold,
                              fontSize: 20)),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(c.name,
                              style: const TextStyle(
                                  fontWeight: FontWeight.w800,
                                  fontSize: 16,
                                  color: AppColors.textPrimary)),
                          if (c.city != null)
                            Text(c.city!,
                                style: const TextStyle(
                                    fontSize: 12,
                                    color: AppColors.textSecondary)),
                        ],
                      ),
                    ),
                    if (c.isSNC)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: Colors.blue.shade50,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text('SNC',
                            style: TextStyle(
                                fontSize: 11,
                                color: Colors.blue.shade700,
                                fontWeight: FontWeight.w700)),
                      ),
                  ],
                ),
                if (c.segment != null || c.status != null) ...[
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    children: [
                      if (c.segment != null)
                        _Chip(label: c.segment!, color: AppColors.primary),
                      if (c.status != null)
                        _Chip(
                            label: c.status!,
                            color: c.status == 'Active'
                                ? Colors.green
                                : Colors.grey),
                    ],
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 12),

          // Info rows
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
              boxShadow: const [
                BoxShadow(color: AppColors.cardShadow, blurRadius: 4)
              ],
            ),
            child: Column(
              children: [
                if (c.address != null)
                  _InfoRow(icon: Icons.location_on_outlined, text: c.address!),
                if (c.phone != null)
                  _InfoRow(icon: Icons.phone_outlined, text: c.phone!),
                if (c.email != null)
                  _InfoRow(icon: Icons.email_outlined, text: c.email!),
                if (c.contactPerson != null)
                  _InfoRow(
                    icon: Icons.person_outline,
                    text: c.contactPerson! +
                        (c.contactPersonPhone != null
                            ? ' · ${c.contactPersonPhone}'
                            : ''),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 20),

          // Contracts section
          Row(
            children: [
              const Text('Kontrak',
                  style: TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 15,
                      color: AppColors.textPrimary)),
              const SizedBox(width: 8),
              if (!_loadingContracts)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.primary.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text('${_contracts.length}',
                      style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.primary,
                          fontWeight: FontWeight.w700)),
                ),
            ],
          ),
          const SizedBox(height: 10),

          if (_loadingContracts)
            const Center(
                child: Padding(
              padding: EdgeInsets.all(24),
              child: CircularProgressIndicator(),
            ))
          else if (_contracts.isEmpty)
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Center(
                child: Text('Belum ada kontrak',
                    style: TextStyle(color: AppColors.textSecondary)),
              ),
            )
          else
            ..._contracts.map((k) => Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _ContractCard(contract: k, onRenew: canEdit
                      ? () async {
                          final ok = await Navigator.push<bool>(
                            context,
                            MaterialPageRoute(
                                builder: (_) => CreateContractScreen(
                                    customer: c,
                                    renewContractId: k.isSNC ? k.id : null)),
                          );
                          if (ok == true) _loadContracts();
                        }
                      : null),
                )),
          const SizedBox(height: 80),
        ],
      ),
    );
  }
}

class _ContractCard extends StatelessWidget {
  final ContractModel contract;
  final VoidCallback? onRenew;
  const _ContractCard({required this.contract, this.onRenew});

  @override
  Widget build(BuildContext context) {
    final k = contract;
    Color statusColor;
    if (!k.isActiveContract) {
      statusColor = Colors.grey;
    } else if (k.isExpired) {
      statusColor = Colors.red;
    } else if (k.isExpiringSoon) {
      statusColor = Colors.orange;
    } else {
      statusColor = Colors.green;
    }

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: statusColor.withOpacity(0.3)),
        boxShadow: const [BoxShadow(color: AppColors.cardShadow, blurRadius: 4)],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(k.noKontrak,
                    style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 14,
                        color: AppColors.textPrimary)),
              ),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: statusColor.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  k.isExpired
                      ? 'Expired'
                      : k.isExpiringSoon
                          ? 'Hampir Habis'
                          : k.isActiveContract
                              ? 'Aktif'
                              : 'Tidak Aktif',
                  style: TextStyle(
                      fontSize: 11,
                      color: statusColor,
                      fontWeight: FontWeight.w700),
                ),
              ),
              if (k.isSNC)
                Padding(
                  padding: const EdgeInsets.only(left: 6),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 6, vertical: 3),
                    decoration: BoxDecoration(
                      color: Colors.blue.shade50,
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text('SNC',
                        style: TextStyle(
                            fontSize: 9,
                            color: Colors.blue.shade700,
                            fontWeight: FontWeight.w700)),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              const Icon(Icons.calendar_today_outlined,
                  size: 13, color: AppColors.textSecondary),
              const SizedBox(width: 4),
              Text(
                '${k.startDate ?? '-'} → ${k.endDate ?? '-'}',
                style: const TextStyle(
                    fontSize: 12, color: AppColors.textSecondary),
              ),
              if (k.daysRemaining != null) ...[
                const SizedBox(width: 8),
                Text(
                  k.isExpired
                      ? '${k.daysRemaining!.abs()} hari lalu'
                      : '${k.daysRemaining} hari lagi',
                  style: TextStyle(
                      fontSize: 11,
                      color: statusColor,
                      fontWeight: FontWeight.w600),
                ),
              ],
            ],
          ),
          if (k.nilaiKontrak != null) ...[
            const SizedBox(height: 4),
            Text(
              'Rp ${_formatRupiah(k.nilaiKontrak!)}',
              style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.textSecondary,
                  fontWeight: FontWeight.w600),
            ),
          ],
          if (onRenew != null && k.isSNC && k.isActiveContract) ...[
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: onRenew,
                icon: const Icon(Icons.autorenew, size: 16),
                label: const Text('Perpanjang'),
                style: TextButton.styleFrom(
                  foregroundColor: AppColors.primary,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  String _formatRupiah(double v) {
    return NumberFormat('#,###', 'id').format(v.round());
  }
}

class _InfoRow extends StatelessWidget {
  final IconData icon;
  final String text;
  const _InfoRow({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 16, color: AppColors.textSecondary),
            const SizedBox(width: 8),
            Expanded(
              child: Text(text,
                  style: const TextStyle(
                      fontSize: 13, color: AppColors.textPrimary)),
            ),
          ],
        ),
      );
}

class _Chip extends StatelessWidget {
  final String label;
  final Color color;
  const _Chip({required this.label, required this.color});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(label,
            style: TextStyle(
                fontSize: 11, color: color, fontWeight: FontWeight.w600)),
      );
}
