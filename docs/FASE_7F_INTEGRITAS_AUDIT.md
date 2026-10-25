# Fase 7F — Integritas audit transmisi

## Tujuan

Fase 7F memperkuat kemampuan operator mengevaluasi integritas audit lokal setelah operasi transmisi dan rekonsiliasi sandbox. Fase ini tidak mengubah database, tidak menambah tabel/kolom, dan tidak memperluas akses jaringan.

## Cakupan

- Gunakan verifikasi hash-chain audit yang sudah tersedia di `rme.security.verify_audit_chain`.
- Tambahkan tes regresi untuk rantai audit kosong, rantai utuh dengan beberapa event, serta deteksi perubahan `details_json`, perubahan hash entri, dan pemutusan `previous_hash`.
- Pastikan verifikasi gagal menunjuk ID entri pertama yang tidak valid, tanpa menampilkan isi audit atau data sensitif.
- Dokumentasikan pemeriksaan sebelum/sesudah rekonsiliasi dan cara memperlakukan hasil yang gagal.

## Interpretasi hasil

- `(True, None)`: seluruh entri yang diperiksa konsisten dengan hash dan urutan predecessor yang tersimpan. Ini bukan bukti bahwa basis data tidak pernah diubah oleh administrator berhak tinggi; hash-chain lokal tidak menggantikan penyimpanan audit eksternal yang append-only.
- `(False, <id>)`: pemeriksaan menemukan entri pertama yang tidak cocok. Hentikan tindakan administrasi lanjutan yang tidak mendesak, pertahankan salinan bukti secara terkendali, dan eskalasi ke penanggung jawab keamanan. Jangan memperbaiki hash secara manual karena itu dapat menghapus jejak perubahan.
- Status transmisi `uncertain` tetap memerlukan rekonsiliasi yang eksplisit. Verifikasi hash audit tidak mengubah status transmisi dan tidak memicu POST/PUT.

## Langkah pemeriksaan operator

1. Jalankan tes CI dan catat commit SHA yang diperiksa.
2. Dalam lingkungan demo lokal yang sesuai, gunakan helper `verify_audit_chain(session)` melalui prosedur administrasi yang ada; jangan membuat endpoint publik baru hanya untuk pemeriksaan ini.
3. Bila verifikasi gagal, simpan waktu pemeriksaan, commit versi aplikasi, dan ID entri pertama yang gagal. Jangan menyertakan token, NIK, data klinis, request/response body atau secret pada tiket.
4. Jangan mengubah status transmisi berdasarkan hasil audit saja. Tinjau ledger transmisi dan hasil rekonsiliasi dengan hak akses yang sesuai.

## Batas keselamatan

- Hanya data sintetis/demonstrasi dalam CI.
- Tidak ada koneksi jaringan ke SATUSEHAT dari CI.
- Tidak ada perubahan skema database atau perubahan default network-off.
- Lolos tes hanya menunjukkan perilaku kode yang diuji; bukan bukti penerimaan resource oleh SATUSEHAT, kepatuhan regulasi, validasi klinis, atau kesiapan produksi.

