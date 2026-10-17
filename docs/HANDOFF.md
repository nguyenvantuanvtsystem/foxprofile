# Handoff — đọc file này đầu tiên trên máy mới

> Toàn bộ ngữ cảnh phiên làm việc tính năng Theo dõi 1 chạm + chép tab.
> Logic chi tiết: `docs/follow-mode.md`. Quy tắc code/test: `CLAUDE.md`.

## 0. Trước khi qua máy khác: PUSH COMMIT ĐI

- Commit `4dc7c6c` (49 files: nút Theo dõi 1 chạm, mirror chép tab, test,
  docs) đang **chỉ nằm local, GitHub chưa có**. Bấm **Push origin** trong
  GitHub Desktop rồi mới sang máy khác, không thì máy kia code cũ.
- Máy mới: `git clone https://github.com/chienbm98/foxprofile.git`,
  checkout đúng commit/branch đó.

## 1. Dựng máy mới (macOS)

```bash
pip install -r requirements-dev.txt
python -m camoufox fetch        # browser engine (bắt buộc để mở profile)
```

- Dữ liệu (`profiles.json`, `camoufox_data/`, `logs/`, `.env`) KHÔNG nằm
  trong repo — theo working directory. Desktop dùng `~/.foxprofile`
  (xem `scripts/run-app.sh`).
- Build Chrome (engine Chrome) tự tải khi cần; profile test live LUÔN
  tạo `engine: "chrome"`.
- Chạy app: `./scripts/run-app.sh` (single-instance, dọn tiến trình mồ côi).
  KHÔNG chạy `python -m src.main` tay, KHÔNG kill backend.
- `FOXPROFILE_LANG=vi` cho tiếng Việt.

## 2. Tính năng vừa xong (có trong commit, máy mới đọc là hiểu)

- **Nút Theo dõi 1 chạm** trên bulk bar: bấm 1 bật / bấm nữa tắt, nút sáng
  cam khi bật. Master = profile tick ĐẦU TIÊN còn chạy; không tick ai thì
  lấy nick chạy đầu tiên; dưới 2 nick chạy thì báo `follow_need_two`.
- **Mirror chép cả tab**: mở/chuyển/đóng tab ở nick chính đều sang follower;
  chuyển trang tại chỗ bám đúng chỉ số (kể cả tab trùng URL); tab lạ scheme
  thành `about:blank` giữ chỗ. Mật khẩu không chép. Chi tiết `follow-mode.md`.
- File chính: `src/ui/handlers.py` (`on_bulk_follow`), `src/ui/state.py`
  (`selection_order`, cờ `follow_active`), `src/services/follow_toggle.py`,
  `src/services/mirror.py`, `src/ui/components/bulk_bar.py`,
  `tests/test_follow_toggle.py`, `tests/test_nuoi_features.py`.

## 3. Việc còn dở (sang máy mới làm tiếp)

1. **App chạy code cũ**: mọi fix mirror (chép tab, bám chỉ số, flag
   `_ensure_injected`) chỉ vào khi restart backend. Restart = dừng nick
   gracefully → Cmd+Q app → `./scripts/run-app.sh` → mở lại nick.
2. Verify cuối trên app thật: tick 3 nick → Theo dõi → mở/đóng/chuyển tab
   ở nick chính, đối chiếu `GET .../page/tabs` các nick còn lại.
3. Test suite: `ruff check`, `ruff format --check`, `pytest` (485+ test).
4. Nhóm (Groups), kho proxy chung — đã chốt thứ tự, chưa code.
5. MCP cho sync/mirror/arrange/extensions — hiện chỉ có API.

## 4. Quyết định đã chốt (đừng đào lại)

- Mỗi nick 1 tiến trình riêng; dừng là hết icon Dock.
- Mirror dùng kênh tiêu đề tab (trang https chặn fetch về localhost).
- Test live: tối đa 2–3 browser, profile test trong scratch
  `FOXPROFILE_DATA_DIR`/`FOXPROFILE_PROFILES_FILE` riêng, xong dừng sạch
  và `ps` xác nhận. Trên nick thật của user: CHỈ bật/tắt mirror + đọc
  status, tuyệt đối không navigate/click/gõ vào trang của user.
- Không commit/push khi chưa được lệnh. `main` đi qua PR.

## 5. Bẫy đã gặp (đừng lặp lại)

- **LaunchAgent `vn.foxprofile.server.plist` chạy `python -m src.server`
  trần (repo data) chiếm cổng 8000, đánh nhau với app desktop** → đã
  `launchctl unload` trên máy cũ. Máy mới: đừng cài agent này cạnh app;
  cần server nền thì đổi cổng/data khác. (File plist nằm ngoài repo,
  `~/Library/LaunchAgents/`, reboot máy cũ nó sống lại.)
- `/tmp` trên macOS bị dọn định kỳ: `profiles.json` scratch đã từng mất.
  Đặt scratch ở chỗ bền hơn hoặc tạo lại khi mất.
- Tool không có quyền kill tiến trình và không có credentials push:
  kill/push nhờ user (Terminal/GitHub Desktop).
- Cuộn trang follower kẹp về 0 nếu follower còn đang load — test cuộn khi
  2 bên đã load xong.
