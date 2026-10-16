# Demo local — Hệ thống gợi ý mỹ phẩm kết nối HDFS

Thư mục nộp demo gồm giao diện trong `fe` và API trong `be`. Web và backend chạy trên máy local. Khi khởi động, backend có thể tự kết nối cụm HDFS qua SSH, đồng bộ gói `serving_export_*.zip` và tạo SQLite cache để phục vụ giao diện nhanh.

HDFS là hệ thống tệp phân tán lưu dữ liệu, không phải cơ sở dữ liệu truy vấn theo request. SQLite chỉ là cache phục vụ ứng dụng; nguồn dữ liệu trung tâm vẫn là HDFS.

## Input, xử lý và output

1. **Input:** gói `serving_export_*.zip` trên HDFS chứa catalog sản phẩm, lịch sử tương tác, Top-K của mô hình `COUNT_C3`, popularity fallback, dashboard và báo cáo đánh giá.
2. **Xử lý:** `be/prepare_data.py` kiểm tra phiên bản trên HDFS. Khi dữ liệu thay đổi, ứng dụng tải ZIP qua SSH và `be/import_data.py` nạp lại SQLite cache. FastAPI cung cấp API cho catalog, lịch sử, gợi ý và dashboard.
3. **Output:** website offline hiển thị sản phẩm theo `product_id` gốc, gợi ý ALS cho user đã biết, popularity fallback cho user mới, lịch sử tương tác và số liệu thực nghiệm.

## Cài đặt lần đầu trên Windows

Yêu cầu: Python 3.10 trở lên và OpenSSH Client của Windows.

Mở Command Prompt tại thư mục `Demo\be`, rồi chạy:

```bat
setup.bat
copy hdfs.env.example.bat hdfs.env.bat
```

Mở `hdfs.env.bat` và điền IP ngoài của `hdfs-master`, user SSH và đường dẫn private key. Tệp này bị Git bỏ qua để không lộ thông tin truy cập.

## Đưa serving export lên HDFS một lần

Sau khi đã cấu hình `hdfs.env.bat`:

```bat
upload_to_hdfs.bat "D:\duong-dan\serving_export_20261015_055252_249418_20261015_101937_261739.zip"
```

Tệp được lưu mặc định tại `/cosmetics/serving/serving_export.zip` trên HDFS. Các CSV gốc trong `/cosmetics/raw` vẫn được giữ cho phần minh chứng lưu trữ phân tán.

## Chạy ứng dụng local

```bat
start.bat
```

`start.bat` tự kiểm tra HDFS. Nếu export thay đổi, nó đồng bộ và tạo lại `be\data\cosmetics.db`; nếu không thay đổi, nó dùng cache hiện có. Khi HDFS tạm thời không truy cập được, ứng dụng tiếp tục chạy bằng cache gần nhất nếu cache đã tồn tại.

Website mở tại <http://127.0.0.1:8000>. API docs ở <http://127.0.0.1:8000/docs>.

Muốn nạp ZIP trực tiếp mà không qua HDFS, vẫn có thể chạy:

```bat
setup.bat "D:\duong-dan\serving_export_....zip"
```

## Cấu trúc

```text
Demo/
├── fe/          # Giao diện web
├── be/          # FastAPI, nhập dữ liệu và lệnh chạy offline
└── README.md    # Hướng dẫn này
```

Không cần API key. Kết nối HDFS từ máy local cần mạng tới VM và khóa SSH hợp lệ. Nếu máy mất mạng hoàn toàn, ứng dụng chỉ dùng được SQLite cache đã đồng bộ trước đó. Không đưa `hdfs.env.bat`, private key, mật khẩu hoặc token vào thư mục nộp.
