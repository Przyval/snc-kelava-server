import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/approvals_provider.dart';
import '../../../core/models/approval_model.dart';
import '../../../core/theme/app_theme.dart';

class ApprovalsScreen extends StatefulWidget {
  const ApprovalsScreen({super.key});

  @override
  State<ApprovalsScreen> createState() => _ApprovalsScreenState();
}

class _ApprovalsScreenState extends State<ApprovalsScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ApprovalsProvider>().load();
    });
  }

  @override
  Widget build(BuildContext context) {
    final prov = context.watch<ApprovalsProvider>();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Persetujuan'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<ApprovalsProvider>().load(),
          ),
        ],
      ),
      body: prov.loading
          ? const Center(child: CircularProgressIndicator())
          : prov.approvals.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.check_circle_outline_rounded,
                          size: 64,
                          color: AppColors.success.withOpacity(0.6)),
                      const SizedBox(height: 16),
                      const Text('Tidak ada yang perlu disetujui',
                          style: TextStyle(
                              color: AppColors.textSecondary, fontSize: 16)),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: () => context.read<ApprovalsProvider>().load(),
                  child: ListView.separated(
                    padding: const EdgeInsets.all(16),
                    itemCount: prov.approvals.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 10),
                    itemBuilder: (ctx, i) =>
                        _ApprovalCard(approval: prov.approvals[i]),
                  ),
                ),
    );
  }
}

class _ApprovalCard extends StatelessWidget {
  final ApprovalModel approval;
  const _ApprovalCard({required this.approval});

  void _showRejectDialog(BuildContext context) {
    final ctrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Tolak Permintaan'),
        content: TextField(
          controller: ctrl,
          decoration: const InputDecoration(
            labelText: 'Alasan penolakan',
            hintText: 'Tuliskan alasan...',
          ),
          maxLines: 3,
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Batal')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.error),
            onPressed: () async {
              Navigator.pop(ctx);
              if (ctrl.text.trim().isNotEmpty) {
                await context
                    .read<ApprovalsProvider>()
                    .reject(approval.id, ctrl.text.trim());
              }
            },
            child: const Text('Tolak', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: const [BoxShadow(color: AppColors.cardShadow, blurRadius: 6)],
        border: Border.all(color: AppColors.warning.withOpacity(0.3)),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.warning.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  approval.actionTypeLabel,
                  style: const TextStyle(
                      color: AppColors.warning,
                      fontWeight: FontWeight.w700,
                      fontSize: 12),
                ),
              ),
              const Spacer(),
              if (approval.createdAt != null)
                Text(
                  DateFormat('d MMM, HH:mm').format(approval.createdAt!),
                  style: const TextStyle(
                      fontSize: 11, color: AppColors.textSecondary),
                ),
            ],
          ),
          const SizedBox(height: 10),
          if (approval.technicianName != null)
            _Row(label: 'Teknisi', value: approval.technicianName!),
          if (approval.customerName != null)
            _Row(label: 'Pelanggan', value: approval.customerName!),
          if (approval.description != null)
            _Row(label: 'Keterangan', value: approval.description!),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => _showRejectDialog(context),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.error,
                    side: const BorderSide(color: AppColors.error),
                  ),
                  icon: const Icon(Icons.close_rounded, size: 16),
                  label: const Text('Tolak'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: () =>
                      context.read<ApprovalsProvider>().approve(approval.id),
                  style:
                      ElevatedButton.styleFrom(backgroundColor: AppColors.success),
                  icon: const Icon(Icons.check_rounded, size: 16, color: Colors.white),
                  label: const Text('Setujui',
                      style: TextStyle(color: Colors.white)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  final String label;
  final String value;
  const _Row({required this.label, required this.value});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 80,
              child: Text(label,
                  style: const TextStyle(
                      fontSize: 12, color: AppColors.textSecondary)),
            ),
            Expanded(
              child: Text(value,
                  style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.textPrimary)),
            ),
          ],
        ),
      );
}
