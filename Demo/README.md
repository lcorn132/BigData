# Demo local — Hệ thống gợi ý mỹ phẩm kết nối HDFS

Thư mục nộp demo gồm giao diện trong `fe` và API trong `be`. Web và backend chạy trên máy local. Khi khởi động, backend có thể tự kết nối cụm HDFS qua SSH, đồng bộ gói `serving_export_*.zip` và tạo SQLite cache để phục vụ giao diện nhanh.

HDFS là hệ thống tệp phân tán lưu dữ liệu, không phải cơ sở dữ liệu truy vấn theo request. SQLite chỉ là cache phục vụ ứng dụng; nguồn dữ liệu trung tâm vẫn là HDFS.

## Input, xử lý và output

1. **Input:** gói `serving_export_*.zip` trên HDFS chứa catalog sản phẩm, lịch sử tương tác, Top-K của mô hình `COUNT_C3`, popularity fallback, dashboard và báo cáo đánh giá.
2. **Xử lý:** `be/prepare_data.py` kiểm tra phiên bản trên HDFS. Khi dữ liệu thay đổi, ứng dụng tải ZIP qua SSH và `be/import_data.py` nạp lại SQLite cache. `be/catalog_enrichment.py` bổ sung lớp nội dung thương mại trình diễn theo `product_id`. FastAPI cung cấp API cho catalog, lịch sử, gợi ý và dashboard.
3. **Output:** website offline có giao diện cửa hàng, tìm kiếm và lọc sản phẩm, chi tiết sản phẩm, giỏ hàng minh họa, gợi ý ALS cho user đã biết, popularity fallback cho user mới, lịch sử tương tác và Dashboard số liệu thực nghiệm.

## Catalog sản phẩm trình diễn

Dataset cosmetics gốc không có tên đầy đủ, mô tả, ảnh, rating hay số lượt đánh giá. Vì vậy ứng dụng phân biệt hai lớp dữ liệu:

- **Dữ liệu thật:** `product_id`, `brand`, `category_id`, `category_code`, `price`, hành vi user, Top-K và toàn bộ metric đánh giá.
- **Dữ liệu sinh cho demo:** `display_name`, `display_brand` khi brand gốc bị thiếu, `product_type`, `description`, `image_key`, `demo_rating`, `demo_review_count` và `demo_badge`.

Các trường demo được sinh xác định bằng SHA-256 của `product_id`, nên một sản phẩm luôn nhận cùng nội dung sau mỗi lần chạy. Chúng được lưu với `enrichment_source = generated_for_demo`, không ghi đè thuộc tính gốc và được ghi chú rõ trên giao diện.

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

`start.bat` tự kiểm tra HDFS. Nếu export thay đổi, nó đồng bộ và tạo lại `be\data\cosmetics.db`; nếu không thay đổi, nó dùng cache hiện có. Sau đó script cập nhật catalog trình diễn cho toàn bộ sản phẩm. Khi HDFS tạm thời không truy cập được, ứng dụng tiếp tục chạy bằng cache gần nhất nếu cache đã tồn tại.

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
