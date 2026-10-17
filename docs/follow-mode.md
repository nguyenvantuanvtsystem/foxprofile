# Chế độ Theo dõi (Follow mode) — logic chuẩn, đừng tự chế lại

Một nút duy nhất trên thanh bulk bar: bấm 1 cái bật, bấm nữa tắt.
Nick tick ĐẦU TIÊN (đang chạy) làm nick chính; các nick đang chạy còn lại
chạy theo cả click/gõ/cuộn/chuyển trang/MỞ-CHUYỂN-ĐÓNG tab.

## Luồng 1 chạm (desktop)

1. `AppHandlers.on_bulk_follow` (`src/ui/handlers.py`) chạy nền:
   - `GET /api/v1/browser/mirror/status` đang bật → `POST .../mirror/stop`,
     tắt cờ `AppState.follow_active`, ghi log `follow_stopped`.
   - Đang tắt → `pick_follow_group(selection_order, running)`:
     master = nick tick đầu tiên còn chạy; không tick ai thì lấy nick chạy
     đầu tiên (sắp xếp); dưới 2 nick chạy thì log `follow_need_two`, dừng.
   - `POST .../mirror/start {master, followers}` → bật cờ, log
     `follow_active`, nút Theo dõi sáng cam (`bulk_bar.py`).
2. Thứ tự tick do `AppState.selection_order()` giữ (`src/ui/state.py`) —
   `set` không nhớ ai tick trước nên KHÔNG được thay bằng `selected_names()`.

## Đầu mirror (server, `src/services/mirror.py`)

- Kênh gesture là tiêu đề tab (`FOXM:<seq>:<base64-json>`), vì trang https
  không POST được về localhost. Chỉ nick chính bị gắn listener
  (`INJECT_JS`), nên không bao giờ dội ngược.
- Poller 0,3 s đọc dải tab của nick chính:
  - Chuyển trang tại chỗ (cùng số tab, đúng tab đang xem đổi URL) →
    follower navigate ĐÚNG CHỈ SỐ tab đó (`navigate_tab`; dải lệch thì
    đối chiếu toàn bộ thay vì đoán) — tab trùng URL không bao giờ lạc.
  - Còn lại (mở/đóng/chuyển tab) → `sync_tabs` đối chiếu cả dải:
    mở URL thiếu (`tab_new`), đóng URL thừa (`tab_close` từ chỉ số lớn),
    chọn tab đang xem: cùng thứ tự thì cùng chỉ số, không thì tab đầu
    cùng URL (`_select_index`, tra chỉ số mới sau mở/đóng để không lệch).
- Tab khác scheme (`chrome://...`) chép thành tab `about:blank` giữ chỗ
  (control chỉ cho `http/https/about:blank`); hai bên đã khớp thì không mở
  lại — cấm "sáng tạo" vòng lặp ở đây.
- Giới hạn 8 lệnh/s/nick; riêng `tab_select` không qua giới hạn để follower
  không kẹt sai tab (sync chỉ chạy lại khi dải của nick chính đổi).
- Mật khẩu và ô file không bao giờ chép. Thứ tự tab giữa các nick có thể
  lệch (không có lệnh di chuyển tab) — chỉ đảm bảo cùng bộ URL + cùng tab
  đang xem.

## API (không đổi, nút 1 chạm gọi đúng 3 cái này)

- `POST /api/v1/browser/mirror/start {master, followers}`
- `POST /api/v1/browser/mirror/stop {}`
- `GET /api/v1/browser/mirror/status` → `{active, master, followers,
  events_in, events_dropped}`

## Test (đã chốt, chạy lại khi đụng vào)

- `tests/test_follow_toggle.py`: chọn master, thứ tự tick, nút sáng/tắt,
  toggle bật/tắt của handler (launcher giả + HTTP vá).
- `tests/test_nuoi_features.py`: `plan_tab_sync`, `_is_inplace_nav`,
  `sync_tabs` với launcher giả.
- Live (code restart mới có hiệu lực): mở 2–3 demo **engine Chrome** trên
  server scratch, bật mirror, mở/chuyển/đóng tab ở master, đối chiếu tab
  follower qua `GET .../page/tabs`, rồi `mirror/stop` + dừng browser + `ps`
  xác nhận sạch. Trên nick thật của user: CHỈ bật/tắt + đọc status, tuyệt
  đối không navigate/click/gõ vào trang của user.
