import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/customer_provider.dart';
import '../../../core/models/customer_model.dart';
import '../../../core/theme/app_theme.dart';
import '../../auth/providers/auth_provider.dart';
import 'create_customer_screen.dart';
import 'customer_detail_screen.dart';

class CustomersScreen extends StatefulWidget {
  const CustomersScreen({super.key});

  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
  final _searchCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<CustomerProvider>().load();
    });
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final prov = context.watch<CustomerProvider>();
    final user = context.watch<AuthProvider>().user;
    final canCreate = user?.isSupervisor ?? false;

    return Scaffold(
      appBar: AppBar(
        title: Text('Pelanggan (${prov.customers.length})'),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: TextField(
              controller: _searchCtrl,
              onChanged: context.read<CustomerProvider>().search,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                hintText: 'Cari nama / kota pelanggan...',
                hintStyle: TextStyle(color: Colors.white.withOpacity(0.7)),
                prefixIcon:
                    Icon(Icons.search, color: Colors.white.withOpacity(0.8)),
                suffixIcon: _searchCtrl.text.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear, color: Colors.white),
                        onPressed: () {
                          _searchCtrl.clear();
                          context.read<CustomerProvider>().search('');
                        },
                      )
                    : null,
                filled: true,
                fillColor: Colors.white.withOpacity(0.2),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(vertical: 10),
              ),
            ),
          ),
        ),
      ),
      floatingActionButton: canCreate
          ? FloatingActionButton.extended(
              onPressed: () async {
                final ok = await Navigator.push<bool>(
                  context,
                  MaterialPageRoute(
                      builder: (_) => const CreateCustomerScreen()),
                );
                if (ok == true && mounted) {
                  context.read<CustomerProvider>().load();
                }
              },
              backgroundColor: AppColors.primary,
              foregroundColor: Colors.white,
              icon: const Icon(Icons.add),
              label: const Text('Tambah Pelanggan'),
            )
          : null,
      body: prov.loading
          ? const Center(child: CircularProgressIndicator())
          : prov.error != null
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(prov.error!,
                          style: TextStyle(color: AppColors.textSecondary)),
                      const SizedBox(height: 12),
                      ElevatedButton(
                        onPressed: () => context.read<CustomerProvider>().load(),
                        child: const Text('Coba Lagi'),
                      ),
                    ],
                  ),
                )
              : prov.customers.isEmpty
                  ? Center(
                      child: Text(
                        'Tidak ada pelanggan ditemukan',
                        style: TextStyle(color: AppColors.textSecondary),
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: () => context.read<CustomerProvider>().load(),
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 16, 16, 80),
                        itemCount: prov.customers.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (ctx, i) => _CustomerCard(
                          customer: prov.customers[i],
                          onTap: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                                builder: (_) => CustomerDetailScreen(
                                    customer: prov.customers[i])),
                          ),
                        ),
                      ),
                    ),
    );
  }
}

class _CustomerCard extends StatelessWidget {
  final CustomerModel customer;
  final VoidCallback onTap;
  const _CustomerCard({required this.customer, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: const [BoxShadow(color: AppColors.cardShadow, blurRadius: 4)],
      ),
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
        leading: CircleAvatar(
          backgroundColor: AppColors.primary.withOpacity(0.12),
          child: Text(
            customer.initials,
            style: const TextStyle(
                color: AppColors.primary, fontWeight: FontWeight.bold),
          ),
        ),
        title: Row(
          children: [
            Expanded(
              child: Text(
                customer.name,
                style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 14,
                    color: AppColors.textPrimary),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            if (customer.isSNC)
              Container(
                margin: const EdgeInsets.only(left: 6),
                padding:
                    const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
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
          ],
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (customer.city != null || customer.address != null)
              Text(
                customer.city ?? customer.address ?? '',
                style: const TextStyle(
                    fontSize: 12, color: AppColors.textSecondary),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            const SizedBox(height: 4),
            Row(
              children: [
                if (customer.segment != null)
                  _Chip(label: customer.segment!, color: AppColors.primary),
                if (customer.status != null)
                  Padding(
                    padding: const EdgeInsets.only(left: 6),
                    child: _Chip(
                      label: customer.status!,
                      color: customer.status == 'Active'
                          ? Colors.green
                          : Colors.grey,
                    ),
                  ),
              ],
            ),
          ],
        ),
        trailing: const Icon(Icons.chevron_right_rounded,
            color: AppColors.textSecondary),
        onTap: onTap,
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final Color color;
  const _Chip({required this.label, required this.color});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(label,
            style: TextStyle(
                fontSize: 10, color: color, fontWeight: FontWeight.w600)),
      );
}
