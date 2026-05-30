-- Migration 028: Replace estimated holidays with SKB 3 Menteri 2026 resmi
-- Source: SKB Menteri Agama + Menteri Ketenagakerjaan + Menteri PANRB
-- User-verified 2026-05-30

-- Clean slate untuk 2026
DELETE FROM snc_suppression_dates WHERE EXTRACT(YEAR FROM suppression_date) = 2026;

-- Hari Libur Nasional 2026 (17 dates)
INSERT INTO snc_suppression_dates (suppression_date, reason) VALUES
  ('2026-01-01', 'Tahun Baru 2026 Masehi'),
  ('2026-01-16', 'Isra Mikraj Nabi Muhammad SAW'),
  ('2026-02-17', 'Tahun Baru Imlek 2577 Kongzili'),
  ('2026-03-19', 'Hari Suci Nyepi (Tahun Baru Saka 1948)'),
  ('2026-03-21', 'Idul Fitri 1447H Hari 1'),
  ('2026-03-22', 'Idul Fitri 1447H Hari 2'),
  ('2026-04-03', 'Wafat Yesus Kristus'),
  ('2026-04-05', 'Kebangkitan Yesus Kristus (Paskah)'),
  ('2026-05-01', 'Hari Buruh Internasional'),
  ('2026-05-14', 'Kenaikan Yesus Kristus'),
  ('2026-05-27', 'Idul Adha 1447H'),
  ('2026-05-31', 'Hari Raya Waisak 2570 BE'),
  ('2026-06-01', 'Hari Lahir Pancasila'),
  ('2026-06-16', '1 Muharam Tahun Baru Islam 1448H'),
  ('2026-08-17', 'Proklamasi Kemerdekaan RI'),
  ('2026-08-25', 'Maulid Nabi Muhammad SAW'),
  ('2026-12-25', 'Kelahiran Yesus Kristus');

-- Cuti Bersama 2026 (8 dates)
INSERT INTO snc_suppression_dates (suppression_date, reason) VALUES
  ('2026-02-16', 'Cuti Bersama Tahun Baru Imlek'),
  ('2026-03-18', 'Cuti Bersama Nyepi'),
  ('2026-03-20', 'Cuti Bersama Idul Fitri'),
  ('2026-03-23', 'Cuti Bersama Idul Fitri'),
  ('2026-03-24', 'Cuti Bersama Idul Fitri'),
  ('2026-05-15', 'Cuti Bersama Kenaikan Yesus Kristus'),
  ('2026-05-28', 'Cuti Bersama Idul Adha'),
  ('2026-12-24', 'Cuti Bersama Natal');
