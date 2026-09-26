import time
import re
from pathlib import Path
import pyperclip
from playwright.sync_api import sync_playwright, expect, TimeoutError as PlaywrightTimeoutError
from matcher import choose_catalog_candidate, norm

BASE_URL = "https://notehrm.vn/"
APP_URL = "https://notehrm.vn/app?id=idkcv"

class NoteHrmError(RuntimeError):
    pass

def _first_visible(page, selectors, timeout=3000):
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible(timeout=timeout):
                return loc.first
        except Exception:
            pass
    return None

def _click_text(page, text, timeout=7000):
    candidates = [
        page.get_by_text(text, exact=True),
        page.locator(f"text={text}"),
        page.locator(f"button:has-text('{text}')"),
        page.locator(f"a:has-text('{text}')"),
    ]
    for loc in candidates:
        try:
            if loc.count():
                for i in range(min(loc.count(), 5)):
                    x = loc.nth(i)
                    if x.is_visible(timeout=1000):
                        x.click()
                        return
        except Exception:
            continue
    raise NoteHrmError(f"Không tìm thấy nút/mục '{text}'.")

def _fill_near_label(page, label_text, value):
    # 1) Semantic label
    try:
        lab = page.get_by_label(label_text, exact=False)
        if lab.count():
            lab.first.fill(value)
            return
    except Exception:
        pass

    # 2) Input/textarea sau node chứa label
    xpath = (
        f"//*[contains(normalize-space(string(.)), '{label_text}')]"
        f"/following::input[not(@type='hidden')][1]"
    )
    loc = page.locator("xpath=" + xpath)
    try:
        if loc.count():
            loc.first.fill(value)
            return
    except Exception:
        pass

    xpath2 = (
        f"//*[contains(normalize-space(string(.)), '{label_text}')]"
        f"/following::textarea[1]"
    )
    loc = page.locator("xpath=" + xpath2)
    try:
        if loc.count():
            loc.first.fill(value)
            return
    except Exception:
        pass

    raise NoteHrmError(f"Không tìm thấy ô '{label_text}'.")

def _click_toolbar_by_title(page, keyword):
    locs = [
        page.locator(f'[title*="{keyword}"]'),
        page.locator(f'[aria-label*="{keyword}"]'),
        page.locator(f'[data-original-title*="{keyword}"]'),
    ]
    for loc in locs:
        try:
            if loc.count():
                for i in range(min(loc.count(), 10)):
                    x = loc.nth(i)
                    if x.is_visible(timeout=500):
                        x.click()
                        return
        except Exception:
            pass
    # fallback: button/icon whose title text contains keyword
    raise NoteHrmError(f"Không tìm thấy nút '{keyword}'.")

def _detect_login(page):
    """Chỉ xác định đang ở màn hình đăng nhập khi CẢ ô mật khẩu
    và nút Đăng nhập thực sự hiển thị. NOTE có thể giữ input mật khẩu
    trong DOM sau khi đăng nhập nên chỉ kiểm tra input[type=password] là sai.
    """
    pwd = _first_visible(page, [
        'input[type="password"]',
        'input[autocomplete="current-password"]',
    ], timeout=700)
    if pwd is None:
        return False

    login_btn = _first_visible(page, [
        'button:has-text("Đăng nhập")',
        'input[type="submit"]',
        'button[type="submit"]',
    ], timeout=700)
    if login_btn is not None:
        return True

    # Fallback: chữ Đăng nhập phải thực sự nhìn thấy.
    try:
        loc = page.get_by_text("Đăng nhập", exact=True)
        for i in range(min(loc.count(), 5)):
            if loc.nth(i).is_visible(timeout=300):
                return True
    except Exception:
        pass
    return False

def _dashboard_visible(page):
    """Các dấu hiệu cho thấy đăng nhập đã thành công và NOTE đã vào hệ thống."""
    indicators = [
        'Nhân sự (HRM)',
        'Phê duyệt điện tử',
        'Công việc',
        'Tổng quan',
    ]
    for text in indicators:
        try:
            loc = page.get_by_text(text, exact=True)
            for i in range(min(loc.count(), 10)):
                if loc.nth(i).is_visible(timeout=250):
                    return True
        except Exception:
            pass
    return False

class NoteHrmAutomation:
    def __init__(self, visible=True, log=None, stop_event=None):
        self.visible = visible
        self.log = log or (lambda x: None)
        self.stop_event = stop_event

    def _check_stop(self):
        if self.stop_event and self.stop_event.is_set():
            raise NoteHrmError("Người dùng đã yêu cầu dừng.")

    def login(self, page, username, password):
        self.log("Mở NOTE HRM...")
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)

        if not _detect_login(page):
            # Có thể đã vào hệ thống hoặc site chuyển hướng.
            if "app" in page.url.lower() or page.get_by_text("Công việc", exact=True).count():
                self.log("Đã có phiên đăng nhập.")
                return
            raise NoteHrmError("Không nhận diện được màn hình đăng nhập NOTE HRM.")

        user = _first_visible(page, [
            'input[name="username"]',
            'input[name="userName"]',
            'input[autocomplete="username"]',
            'input[type="text"]',
            'input[type="email"]',
        ], timeout=5000)
        pwd = _first_visible(page, [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ], timeout=5000)
        if not user or not pwd:
            raise NoteHrmError("Không tìm thấy ô tài khoản/mật khẩu.")

        user.fill(username)
        pwd.fill(password)

        btn = _first_visible(page, [
            'button:has-text("Đăng nhập")',
            'input[type="submit"]',
            'button[type="submit"]',
        ], timeout=3000)
        if not btn:
            try:
                _click_text(page, "Đăng nhập", timeout=3000)
            except Exception as e:
                raise NoteHrmError("Không tìm thấy nút Đăng nhập.") from e
        else:
            btn.click()

        # NOTE có thể mất vài giây để chuyển từ form đăng nhập sang màn hình
        # tổng quan. Không kiểm tra input[type=password] ngay sau 1.5 giây vì
        # control đăng nhập có thể vẫn còn trong DOM dù đã đăng nhập thành công.
        login_ok = False
        deadline = time.time() + 15
        while time.time() < deadline:
            self._check_stop()

            if _dashboard_visible(page):
                login_ok = True
                break

            # CAPTCHA/OTP/login error: dừng, không cố vượt qua.
            try:
                body = page.locator("body").inner_text(timeout=1000).lower()
            except Exception:
                body = ""
            if any(k in body for k in ["captcha", "mã otp", "otp", "xác thực hai lớp"]):
                raise NoteHrmError(
                    "Trang yêu cầu CAPTCHA/OTP/xác thực bổ sung; tool dừng để người dùng xử lý thủ công."
                )

            page.wait_for_timeout(500)

        if not login_ok:
            # Chỉ kết luận đăng nhập thất bại nếu form đăng nhập thực sự còn
            # hiển thị. Nếu không còn form nhưng cũng chưa nhận diện được
            # dashboard thì báo lỗi chuyển trang thay vì báo sai 'vẫn còn màn hình đăng nhập'.
            if _detect_login(page):
                raise NoteHrmError("Đăng nhập thất bại: vẫn còn màn hình đăng nhập.")
            raise NoteHrmError(
                "Đã gửi đăng nhập nhưng sau 15 giây chưa nhận diện được màn hình NOTE HRM sau đăng nhập."
            )

        self.log("Đăng nhập thành công.")

    def ensure_hrm_module(self, page):
        """Xử lý màn hình sau đăng nhập: nếu thấy card Nhân sự (HRM) thì click vào."""
        self._check_stop()

        # Ưu tiên đúng tình huống người dùng cung cấp: màn hình tổng quan có card
        # "Nhân sự (HRM)". Dù sidebar đã có chữ "Công việc", vẫn click card HRM trước.
        hrm_candidates = [
            page.get_by_text("Nhân sự (HRM)", exact=True),
            page.locator('button:has-text("Nhân sự (HRM)")'),
            page.locator('a:has-text("Nhân sự (HRM)")'),
            page.get_by_text("Nhân sự (HRM)", exact=False),
        ]
        for loc in hrm_candidates:
            try:
                for i in range(min(loc.count(), 10)):
                    x = loc.nth(i)
                    if x.is_visible(timeout=500):
                        self.log("Phát hiện màn hình tổng quan; chọn Nhân sự (HRM)...")
                        x.click()
                        page.wait_for_timeout(1200)
                        self.log("Đã vào phân hệ Nhân sự (HRM).")
                        return
            except Exception:
                pass

        # Nếu không có card HRM, có thể tài khoản đã vào thẳng giao diện nghiệp vụ.
        try:
            loc = page.get_by_text("Công việc", exact=True)
            for i in range(min(loc.count(), 5)):
                x = loc.nth(i)
                if x.is_visible(timeout=500):
                    self.log("Đã ở giao diện có phân hệ Công việc; bỏ qua bước chọn Nhân sự (HRM).")
                    return
        except Exception:
            pass

        raise NoteHrmError(
            "Sau khi đăng nhập không tìm thấy nút 'Nhân sự (HRM)' và cũng không nhận diện được giao diện Công việc."
        )

    def logout(self, page):
        """Đăng xuất sau khi tài khoản hiện tại lưu phiếu thành công."""
        self._check_stop()
        self.log("Đang đăng xuất tài khoản hiện tại...")
        logout_item = page.locator('div.logout-text').filter(visible=True)
        if not logout_item.count():
            account = page.locator('#SysUserBox button.navbar-login').first
            if not account.is_visible(timeout=5000):
                raise NoteHrmError("Đã lưu phiếu nhưng không thấy tài khoản #SysUserBox để đăng xuất.")
            account.click()
        try:
            logout_item.first.wait_for(state='visible', timeout=5000)
            logout_item.first.click()
        except PlaywrightTimeoutError as error:
            raise NoteHrmError("Đã lưu phiếu nhưng không tìm thấy mục Đăng xuất trong menu tài khoản.") from error

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if _detect_login(page):
                self.log("Đăng xuất thành công; đã về màn hình đăng nhập.")
                return
            page.wait_for_timeout(400)
        raise NoteHrmError(
            "Đã nhấn Đăng xuất nhưng chưa xác nhận được màn hình đăng nhập. "
            "Dừng hàng đợi để tránh dùng nhầm tài khoản."
        )

    def open_registration(self, page):
        self._check_stop()
        self.log("Vào Công việc → Đăng ký...")
        try:
            _click_text(page, "Công việc")
        except Exception:
            pass
        page.wait_for_timeout(500)
        _click_text(page, "Đăng ký")
        page.wait_for_timeout(1000)
        self.log("Mở màn hình Đăng ký.")

    def click_add(self, page):
        """Click đúng nút Thêm trên toolbar màn hình Đăng ký.

        V5: giữ nguyên toàn bộ luồng đang chạy ổn định. Chỉ thay cơ chế tìm/click
        nút Thêm. Giao diện NOTE dùng button có thể chứa icon + span chữ Thêm,
        vì vậy không phụ thuộc duy nhất vào role/text node.
        """
        self._check_stop()
        self.log("Tìm nút Thêm trên toolbar...")

        # 0) NOTE thực tế render nút Thêm bằng:
        #    <div xcode="add" class="quick-toolbar-item add">...
        #    Chữ "Thêm" nằm trong <label>, vì vậy get_by_text("Thêm") có thể
        #    bị chính div cha intercept pointer events. Ưu tiên đúng phần tử
        #    toolbar này để không phụ thuộc co giãn header/layout.
        try:
            add_nodes = page.locator('[xcode="add"], .quick-toolbar-item.add')
            for i in range(min(add_nodes.count(), 10)):
                node = add_nodes.nth(i)
                if not node.is_visible(timeout=200):
                    continue
                box = node.bounding_box()
                if not box or box["y"] > 180 or box["width"] <= 0 or box["height"] <= 0:
                    continue
                self.log(
                    f"Đã xác định nút Thêm tại x={int(box["x"])} , y={int(box["y"])}."
                )
                try:
                    node.click(timeout=3000, force=True)
                except Exception:
                    node.evaluate("el => el.click()")
                page.wait_for_timeout(1000)
                # Xác nhận form trước khi đi tiếp.
                inputs = page.locator("input:not([type='hidden']), textarea")
                if inputs.count() >= 4 or page.get_by_text("Tên kế hoạch công việc", exact=False).count():
                    self.log("Đã mở màn hình Thêm.")
                    return
        except Exception:
            pass

        # 1) Ưu tiên các button có chữ Thêm và nằm ở vùng toolbar phía trên.
        candidates = []
        locators = [
            page.locator("button"),
            page.locator('[role="button"]'),
            page.locator("a"),
            page.locator(".btn"),
            page.get_by_text("Thêm", exact=True),
        ]

        viewport = page.viewport_size or {"width": 1600, "height": 900}
        vw = viewport.get("width", 1600)

        for loc in locators:
            try:
                count = min(loc.count(), 100)
                for i in range(count):
                    el = loc.nth(i)
                    try:
                        if not el.is_visible():
                            continue
                        box = el.bounding_box()
                        if not box:
                            continue
                        txt = (el.inner_text(timeout=100) or "").strip()
                        # Chấp nhận button có icon + chữ Thêm, nhưng loại các
                        # phần tử chứa cả câu dài hoặc menu khác.
                        normalized = " ".join(txt.split())
                        if normalized != "Thêm":
                            continue
                        x, y, w, h = box["x"], box["y"], box["width"], box["height"]
                        # Nút Thêm trên toolbar nằm phía trên; không yêu cầu
                        # cứng x > 55% vì kích thước browser có thể thay đổi.
                        if y <= 180 and w <= 240 and h <= 120:
                            candidates.append((el, box))
                    except Exception:
                        continue
            except Exception:
                continue

        # Loại duplicate locator, ưu tiên nút ở bên phải và gần phía trên.
        unique = []
        seen = set()
        for el, box in candidates:
            key = (round(box["x"]), round(box["y"]), round(box["width"]), round(box["height"]))
            if key not in seen:
                seen.add(key)
                unique.append((el, box))
        candidates = unique

        if candidates:
            candidates.sort(key=lambda z: (z[1]["y"], -z[1]["x"]))
            target, target_box = candidates[0]
            self.log(
                f"Đã xác định nút Thêm tại x={int(target_box["x"])} , y={int(target_box["y"])}."
            )
        else:
            target = None
            target_box = None

        # 2) Nếu button/role không bắt được, tìm node chữ 'Thêm' rồi leo lên
        # ancestor có khả năng click được.
        if target is None:
            text_nodes = page.get_by_text("Thêm", exact=True)
            try:
                count = min(text_nodes.count(), 30)
                for i in range(count):
                    node = text_nodes.nth(i)
                    if not node.is_visible():
                        continue
                    box = node.bounding_box()
                    if not box or box["y"] > 180:
                        continue
                    parent = node.locator(
                        "xpath=ancestor::*[self::button or self::a or @role='button' "
                        "or contains(concat(' ', normalize-space(@class), ' '), ' btn ')][1]"
                    )
                    if parent.count() and parent.first.is_visible():
                        target = parent.first
                        target_box = target.bounding_box()
                        if target_box:
                            self.log(
                                f"Đã tìm thấy nút Thêm qua phần tử cha tại x={int(target_box["x"])} , y={int(target_box["y"])}."
                            )
                            break
            except Exception:
                pass

        if target is None:
            # 3) Fallback cuối: tìm trực tiếp trong DOM bằng JavaScript theo
            # text + vị trí. Không click phần tử khác nếu không đúng chữ Thêm.
            try:
                handle = page.evaluate_handle("""
                    () => {
                      const els = Array.from(document.querySelectorAll('button,a,[role="button"],.btn,div,span'));
                      const arr = els.filter(el => {
                        const r = el.getBoundingClientRect();
                        const t = (el.innerText || '').trim().replace(/\\s+/g, ' ');
                        return t === 'Thêm' && r.width > 0 && r.height > 0 && r.top <= 180 && r.width <= 240 && r.height <= 120;
                      });
                      arr.sort((a,b) => b.getBoundingClientRect().left - a.getBoundingClientRect().left);
                      return arr[0] || null;
                    }
                """)
                target = handle.as_element()
                if target:
                    target_box = target.bounding_box()
            except Exception:
                target = None

        if target is None:
            raise NoteHrmError("Không tìm thấy nút Thêm trên màn hình Đăng ký.")

        def add_form_visible():
            # Form sau khi bấm Thêm có thể dùng label hoặc input; chỉ cần thấy
            # ít nhất 2 dấu hiệu là đủ xác nhận đã mở form.
            markers = [
                "Tên kế hoạch công việc",
                "Ngày bắt đầu",
                "Ngày kết thúc",
                "Nội dung",
            ]
            hits = 0
            for text in markers:
                try:
                    loc = page.get_by_text(text, exact=False)
                    for i in range(min(loc.count(), 10)):
                        if loc.nth(i).is_visible():
                            hits += 1
                            break
                except Exception:
                    pass
            if hits >= 2:
                return True

            # Nếu form dùng placeholder/name thay vì text label.
            try:
                visible_inputs = page.locator("input:not([type='hidden']), textarea").count()
                return visible_inputs >= 4 and page.url != APP_URL
            except Exception:
                return False

        # 4) Click chuẩn vào phần tử đã xác định.
        try:
            target.scroll_into_view_if_needed(timeout=2000)
            target.click(timeout=5000, force=False)
            page.wait_for_timeout(1000)
            if add_form_visible():
                self.log("Đã mở màn hình Thêm.")
                return
        except Exception as e:
            self.log(f"Click chuẩn nút Thêm không thành công: {type(e).__name__}: {e}")

        # 5) Click force: chỉ trên chính target, không tìm lại phần tử khác.
        try:
            target.click(timeout=3000, force=True)
            page.wait_for_timeout(1000)
            if add_form_visible():
                self.log("Đã mở màn hình Thêm.")
                return
        except Exception as e:
            self.log(f"Force click nút Thêm không thành công: {type(e).__name__}: {e}")

        # 6) Click tâm nút.
        try:
            box = target.bounding_box()
            if box:
                self.log("Thử click trực tiếp vào tâm nút Thêm...")
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.wait_for_timeout(1000)
                if add_form_visible():
                    self.log("Đã mở màn hình Thêm.")
                    return
        except Exception as e:
            self.log(f"Click tọa độ nút Thêm không thành công: {type(e).__name__}: {e}")

        # 7) JS click trên đúng target cuối cùng.
        try:
            target.evaluate("el => el.click()")
            page.wait_for_timeout(1200)
            if add_form_visible():
                self.log("Đã mở màn hình Thêm.")
                return
        except Exception as e:
            self.log(f"JS click nút Thêm không thành công: {type(e).__name__}: {e}")

        try:
            Path("logs").mkdir(exist_ok=True)
            page.screenshot(path="logs/error_click_add.png", full_page=True)
        except Exception:
            pass

        raise NoteHrmError(
            "Đã xác định đúng vùng nút Thêm nhưng không mở được màn hình nhập mới. "
            "Tool dừng để tránh thao tác nhầm. Xem logs/error_click_add.png."
        )

    def fill_header(self, page, plan_name, content,
                    start_date='01/07/2026', end_date='30/09/2026'):
        self._check_stop()
        self.log("Điền thông tin chung...")
        # The list behind the new form contains filter inputs with the same
        # field names. Only .input-field belongs to the open edit form.
        fields = {
            'ngay_hl1': start_date,
            'ngay_hl2': end_date,
            'ten_cv': plan_name,
            'noi_dung': content,
        }
        for field, value in fields.items():
            matches = page.locator(f'input.input-field.{field}')
            visible = [matches.nth(i) for i in range(matches.count())
                       if matches.nth(i).is_visible()]
            if len(visible) != 1:
                raise NoteHrmError(
                    f"Không xác định duy nhất ô thông tin chung '{field}' "
                    f"(tìm thấy {len(visible)} ô)."
                )
            visible[0].fill(value)
            visible[0].press('Tab')
            actual = visible[0].input_value().strip()
            if actual != str(value).strip():
                raise NoteHrmError(
                    f"Ô '{field}' nhận '{actual}' thay vì '{value}'."
                )

    def _find_grid_header(self, page, header_text):
        """Tìm tiêu đề cột NOTE ổn định hơn V6.

        V6 chủ yếu dùng get_by_text(), nhưng grid NOTE có thể render chữ
        trong div/span lồng nhau khiến locator không bắt được. V7 giữ nguyên
        cách cũ trước, sau đó fallback quét DOM bằng textContent và vị trí.
        """
        target = " ".join(str(header_text).split()).strip().lower()

        # 1) Giữ nguyên cách tìm của V6.
        candidates = [
            page.get_by_text(header_text, exact=True),
            page.get_by_text(header_text, exact=False),
            page.locator('th'),
            page.locator('[role="columnheader"]'),
        ]
        for loc in candidates:
            try:
                for i in range(min(loc.count(), 100)):
                    x = loc.nth(i)
                    if not x.is_visible(timeout=200):
                        continue
                    box = x.bounding_box()
                    if not box or box["y"] < 90 or box["y"] > 650:
                        continue
                    txt = " ".join((x.inner_text(timeout=100) or "").split()).strip().lower()
                    if txt == target or target in txt:
                        return x
            except Exception:
                pass

        # 2) Fallback DOM: exact textContent, không phụ thuộc tag/class.
        try:
            handle = page.evaluate_handle("""
                (target) => {
                    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const nodes = Array.from(document.querySelectorAll('*'));
                    const matches = [];
                    for (const el of nodes) {
                        const r = el.getBoundingClientRect();
                        if (!r || r.width <= 0 || r.height <= 0) continue;
                        if (r.top < 90 || r.top > 650) continue;
                        if (norm(el.textContent) !== target) continue;

                        const tag = el.tagName.toLowerCase();
                        const cls = String(el.className || '').toLowerCase();
                        const role = String(el.getAttribute('role') || '').toLowerCase();
                        let score = 0;
                        if (tag === 'th') score += 100;
                        if (role === 'columnheader') score += 90;
                        if (cls.includes('header')) score += 30;
                        if (cls.includes('column')) score += 20;
                        if (r.top >= 100 && r.top <= 400) score += 10;
                        matches.push({el, score, top:r.top, left:r.left, area:r.width*r.height});
                    }
                    matches.sort((a,b) => b.score-a.score || a.top-b.top || a.left-b.left || a.area-b.area);
                    return matches.length ? matches[0].el : null;
                }
            """, target)
            el = handle.as_element()
            if el:
                box = el.bounding_box()
                if box:
                    self.log(f"Đã nhận diện tiêu đề cột '{header_text}' qua DOM tại x={int(box["x"])}, y={int(box["y"])}.")
                return el
        except Exception:
            pass

        # 3) Fallback: tìm node có text gần đúng trong vùng grid.
        try:
            handle = page.evaluate_handle("""
                (target) => {
                    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const nodes = Array.from(document.querySelectorAll('*'));
                    const matches = [];
                    for (const el of nodes) {
                        const r = el.getBoundingClientRect();
                        if (!r || r.width <= 0 || r.height <= 0 || r.top < 90 || r.top > 650) continue;
                        const txt = norm(el.textContent);
                        if (txt === target || txt.includes(target)) {
                            matches.push({el, area:r.width*r.height, top:r.top});
                        }
                    }
                    matches.sort((a,b) => a.area-b.area || a.top-b.top);
                    return matches.length ? matches[0].el : null;
                }
            """, target)
            el = handle.as_element()
            if el:
                return el
        except Exception:
            pass

        return None

    def _click_grid_data_cell_under_header(self, page, header_text, row_index=0):
        """Chọn đúng ô dữ liệu trong *chính bảng* chứa header.

        V13: fix riêng lỗi click nhầm header ``Ngày thực hiện`` làm NOTE mở
        ``#grid_popup_menu`` (Ẩn cột / Tùy chỉnh các cột).

        Nguyên tắc mới:
        1. Tìm node header theo text.
        2. Từ header đi lên ``closest('table')`` để khóa đúng bảng Chi tiết.
        3. Tìm ``thead th`` để lấy đúng chỉ số cột.
        4. Lấy ``tbody tr[row_index]`` của CHÍNH table đó.
        5. Lấy ``td`` cùng chỉ số cột và click chính cell, tuyệt đối không click
           lại header hoặc quét ``table tbody tr`` trên toàn trang.

        Các luồng khác không thay đổi.
        """
        self._check_stop()
        target = " ".join(str(header_text).split()).strip().lower()

        # Nếu menu ngữ cảnh của grid đang còn mở từ một thao tác trước đó,
        # đóng nó trước khi chọn cell. Không thao tác lên dữ liệu.
        try:
            page.evaluate("""
                () => {
                    const m = document.querySelector('#grid_popup_menu');
                    if (m) {
                        m.style.display = 'none';
                        m.classList.remove('show');
                    }
                }
            """)
        except Exception:
            pass

        # Tìm header và table cha bằng DOM thuần để tránh locator nhảy sang
        # một table khác trên trang.
        handle = None
        try:
            handle = page.evaluate_handle("""
                (target) => {
                    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const nodes = Array.from(document.querySelectorAll('th, [role="columnheader"]'));
                    const matches = [];
                    for (const el of nodes) {
                        const r = el.getBoundingClientRect();
                        if (!r || r.width <= 0 || r.height <= 0) continue;
                        if (norm(el.textContent) !== target) continue;
                        const table = el.closest('table');
                        if (!table) continue;
                        const tr = el.closest('tr');
                        if (!tr) continue;
                        const cells = Array.from(tr.children);
                        const colIndex = cells.indexOf(el);
                        if (colIndex < 0) continue;
                        const tableRect = table.getBoundingClientRect();
                        let score = 0;
                        const id = String(table.id || '').toLowerCase();
                        const cls = String(table.className || '').toLowerCase();
                        if (id.includes('idkcv')) score += 100;
                        if (id.includes('table')) score += 10;
                        if (cls.includes('table-multi')) score += 10;
                        if (tableRect.width > 500) score += 5;
                        matches.push({el, score, top:r.top, left:r.left, colIndex});
                    }
                    matches.sort((a,b) => b.score-a.score || a.top-b.top || a.left-b.left);
                    if (!matches.length) return null;
                    const m = matches[0];
                    m.el.dataset.__notehrm_col_index = String(m.colIndex);
                    return m.el;
                }
            """, target)
        except Exception as e:
            raise NoteHrmError(
                f"Không xác định được tiêu đề cột '{header_text}': {type(e).__name__}: {e}"
            ) from e

        header = handle.as_element() if handle else None
        if header is None:
            raise NoteHrmError(f"Không tìm thấy tiêu đề cột '{header_text}'.")

        hb = header.bounding_box()
        if not hb:
            raise NoteHrmError(f"Không lấy được vị trí cột '{header_text}'.")

        # Lấy table cha + index cột từ chính DOM header.
        try:
            info = page.evaluate("""
                (el) => {
                    const table = el.closest('table');
                    const headRow = el.closest('tr');
                    if (!table || !headRow) return null;
                    const headCells = Array.from(headRow.children);
                    const colIndex = headCells.indexOf(el);
                    const bodyRows = Array.from(table.querySelectorAll('tbody tr'))
                        .filter(r => {
                            const x = r.getBoundingClientRect();
                            return x && x.width > 0 && x.height > 0;
                        });
                    return {
                        tableId: table.id || '',
                        tableClass: String(table.className || ''),
                        colIndex,
                        bodyCount: bodyRows.length,
                        headerBottom: el.getBoundingClientRect().bottom
                    };
                }
            """, header)
        except Exception:
            info = None

        if not info or info.get("colIndex", -1) < 0:
            raise NoteHrmError(f"Không xác định được vị trí cột '{header_text}' trong bảng.")

        col_index = int(info["colIndex"])
        body_count = int(info.get("bodyCount", 0))
        if body_count <= row_index:
            raise NoteHrmError(
                f"Không tìm thấy dòng dữ liệu {row_index + 1} của cột '{header_text}'."
            )

        self.log(
            f"Đã xác định cột '{header_text}' trong bảng '{info.get('tableId') or info.get('tableClass')}', "
            f"cột index={col_index}."
        )

        # Lấy đúng row + td theo cùng table và cùng column index.
        cell_handle = page.evaluate_handle("""
            ({target, rowIndex, colIndex}) => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const headers = Array.from(document.querySelectorAll('th, [role="columnheader"]'));
                let header = null;
                for (const h of headers) {
                    if (norm(h.textContent) === target) {
                        const table = h.closest('table');
                        const tr = h.closest('tr');
                        if (!table || !tr) continue;
                        const cells = Array.from(tr.children);
                        if (cells.indexOf(h) === colIndex) {
                            header = h;
                            break;
                        }
                    }
                }
                if (!header) return null;
                const table = header.closest('table');
                const rows = Array.from(table.querySelectorAll('tbody tr')).filter(r => {
                    const rbox = r.getBoundingClientRect();
                    return rbox && rbox.width > 0 && rbox.height > 0;
                });
                const row = rows[rowIndex];
                if (!row) return null;
                const cells = Array.from(row.children).filter(c => {
                    const cbox = c.getBoundingClientRect();
                    return cbox && cbox.width > 0 && cbox.height > 0;
                });
                return cells[colIndex] || null;
            }
        """, {"target": target, "rowIndex": row_index, "colIndex": col_index})

        cell = cell_handle.as_element() if cell_handle else None
        if cell is None:
            raise NoteHrmError(
                f"Không tìm thấy ô dữ liệu dòng {row_index + 1}, cột '{header_text}'."
            )

        cb = cell.bounding_box()
        if not cb or cb["width"] <= 0 or cb["height"] <= 0:
            raise NoteHrmError(f"Ô dữ liệu '{header_text}' không có vị trí hiển thị hợp lệ.")

        self.log(
            f"Đã xác định ô dữ liệu '{header_text}' dòng {row_index + 1} "
            f"tại x={int(cb['x'])}, y={int(cb['y'])}."
        )

        # Click đúng cell. Không click header, không click theo tâm cột.
        # Ưu tiên mouse events + click() của chính cell để NOTE xử lý editor.
        clicked = False
        last_error = None
        for method in ("dom", "force", "mouse"):
            try:
                if method == "dom":
                    cell.evaluate("""
                        el => {
                            el.scrollIntoView({block: 'center', inline: 'nearest'});
                            el.focus && el.focus();
                            el.dispatchEvent(new MouseEvent('mousedown', {
                                bubbles: true, cancelable: true, view: window
                            }));
                            el.dispatchEvent(new MouseEvent('mouseup', {
                                bubbles: true, cancelable: true, view: window
                            }));
                            el.click();
                        }
                    """)
                elif method == "force":
                    cell.click(timeout=2500, force=True)
                else:
                    cb = cell.bounding_box()
                    if not cb:
                        continue
                    page.mouse.click(cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2)

                page.wait_for_timeout(350)
                clicked = True
                break
            except Exception as e:
                last_error = e

        if not clicked:
            raise NoteHrmError(
                f"Không thể chọn ô dữ liệu cột '{header_text}': "
                f"{type(last_error).__name__}: {last_error}"
            ) from last_error

        # Kiểm tra nhẹ: NOTE thường tạo input editor .ngay_th khi ô ngày được
        # chọn. Không bắt buộc input phải xuất hiện vì có phiên bản chỉ đổi class.
        try:
            editor = page.locator('input.grid-input-field.ngay_th')
            if editor.count() and editor.last.is_visible(timeout=500):
                self.log("Ô Ngày thực hiện đã được kích hoạt; editor ngày đang nhận focus.")
        except Exception:
            pass

    def _click_grid_toolbar_action(self, page, action_name, aliases, fallback_index=None):
        """Click icon trên toolbar của bảng chi tiết bằng nhiều lớp nhận diện.

        NOTE có thể render icon bằng <i>, <span>, SVG hoặc button không có text,
        nên không chỉ dựa vào title/aria-label. Hàm này dùng:
        1) title/aria-label/data-original-title;
        2) class/name có từ khóa;
        3) phần tử click được nằm trong toolbar;
        4) fallback theo thứ tự icon nếu giao diện không gắn metadata.
        """
        self._check_stop()
        alias_low = [a.lower() for a in aliases]

        def attr_text(el):
            vals = []
            for attr in ["title", "aria-label", "data-original-title", "data-tip", "name", "class"]:
                try:
                    vals.append(el.get_attribute(attr) or "")
                except Exception:
                    pass
            try:
                vals.append(el.inner_text(timeout=50) or "")
            except Exception:
                pass
            return " ".join(vals).lower()

        # Xác định vùng toolbar dựa trên dòng dữ liệu đầu tiên.
        data_y = None
        for sel in ["table tbody tr", '[role="row"]', ".wj-row"]:
            try:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 50)):
                    r = loc.nth(i)
                    if not r.is_visible(timeout=100):
                        continue
                    rb = r.bounding_box()
                    if rb and rb["y"] > 200:
                        data_y = rb["y"]
                        break
                if data_y is not None:
                    break
            except Exception:
                pass

        if data_y is None:
            data_y = 350

        toolbar_min_y = max(100, data_y - 90)
        toolbar_max_y = data_y - 2

        # Lớp 0: NOTE dùng .quick-toolbar-item cho các icon của bảng chi tiết.
        # Đây là lớp ưu tiên vì icon Dán dữ liệu có thể không có title/aria-label
        # và cũng không phải button/i/span. Trong giao diện hiện tại, thứ tự trái
        # -> phải của nhóm này là: Thêm, Xóa, Sao chép, Dán dữ liệu, ...
        # Chỉ lấy các item nằm ngay phía trên dòng dữ liệu của chính grid.
        try:
            qt = page.locator(".quick-toolbar-item")
            qt_items = []
            for i in range(min(qt.count(), 100)):
                el = qt.nth(i)
                if not el.is_visible(timeout=50):
                    continue
                box = el.bounding_box()
                if not box or box["width"] <= 0 or box["height"] <= 0:
                    continue
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                if data_y is not None:
                    # Toolbar grid thường nằm ngay phía trên dòng đầu tiên.
                    if not (data_y - 90 <= cy <= data_y + 5):
                        continue
                txt = attr_text(el)
                qt_items.append((box["x"], box["y"], el, txt))

            # Gộp theo vị trí x để không bị trùng do node con.
            groups = []
            for x, y, el, txt in sorted(qt_items, key=lambda z: (z[1], z[0])):
                placed = False
                for g in groups:
                    if abs(g[0] - x) <= 12 and abs(g[1] - y) <= 12:
                        # Ưu tiên node ngoài có diện tích lớn hơn.
                        old = g[2]
                        try:
                            ob = old.bounding_box()
                            nb = el.bounding_box()
                            if nb and (not ob or nb["width"] * nb["height"] > ob["width"] * ob["height"]):
                                g[2] = el
                                g[3] = txt
                        except Exception:
                            pass
                        placed = True
                        break
                if not placed:
                    groups.append([x, y, el, txt])

            groups.sort(key=lambda g: (g[1], g[0]))

            # Ưu tiên metadata/xcode ngay trên quick-toolbar-item.
            for x, y, el, txt in groups:
                if any(a in txt for a in alias_low):
                    try:
                        el.click(timeout=2500, force=True)
                        page.wait_for_timeout(400)
                        self.log(f"Đã click icon '{action_name}' qua quick-toolbar metadata.")
                        return
                    except Exception:
                        try:
                            el.evaluate("el => el.click()")
                            page.wait_for_timeout(400)
                            self.log(f"Đã click icon '{action_name}' qua quick-toolbar DOM.")
                            return
                        except Exception:
                            pass

            # Fallback theo vị trí: Dán dữ liệu là item thứ 4 từ trái trong
            # toolbar của bảng chi tiết hiện tại. Chỉ dùng khi có đủ 4 item.
            if fallback_index is not None and len(groups) > fallback_index:
                el = groups[fallback_index][2]
                try:
                    el.click(timeout=2500, force=True)
                    page.wait_for_timeout(400)
                    self.log(
                        f"Đã click icon '{action_name}' theo quick-toolbar (icon thứ {fallback_index + 1})."
                    )
                    return
                except Exception:
                    try:
                        el.evaluate("el => el.click()")
                        page.wait_for_timeout(400)
                        self.log(
                            f"Đã click icon '{action_name}' theo quick-toolbar DOM (icon thứ {fallback_index + 1})."
                        )
                        return
                    except Exception:
                        pass
        except Exception:
            pass

        # Lớp 1: metadata.
        meta_selectors = [
            '[title]', '[aria-label]', '[data-original-title]', '[data-tip]',
            'button', '[role="button"]', 'a', 'i', 'span'
        ]
        seen = set()
        for sel in meta_selectors:
            try:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 800)):
                    el = loc.nth(i)
                    if not el.is_visible(timeout=50):
                        continue
                    box = el.bounding_box()
                    if not box:
                        continue
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    if not (toolbar_min_y <= cy <= toolbar_max_y):
                        continue
                    if box["width"] > 100 or box["height"] > 80:
                        continue
                    key = (round(box["x"]), round(box["y"]), round(box["width"]), round(box["height"]))
                    if key in seen:
                        continue
                    seen.add(key)
                    txt = attr_text(el)
                    if any(a in txt for a in alias_low):
                        try:
                            el.click(timeout=2500)
                            page.wait_for_timeout(400)
                            self.log(f"Đã click icon '{action_name}' qua metadata.")
                            return
                        except Exception:
                            # Nếu node là span/i, thử phần tử cha có thể click.
                            try:
                                parent = el.locator(
                                    "xpath=ancestor::*[self::button or self::a or @role='button' "
                                    "or contains(concat(' ', normalize-space(@class), ' '), ' btn ')][1]"
                                )
                                if parent.count() and parent.first.is_visible():
                                    parent.first.click(timeout=2500)
                                    page.wait_for_timeout(400)
                                    self.log(f"Đã click icon '{action_name}' qua phần tử cha.")
                                    return
                            except Exception:
                                pass
            except Exception:
                pass

        # Lớp 2: gom các phần tử nhỏ/clickable trong toolbar theo vị trí.
        # Dùng khi icon không có title/aria-label. Thứ tự trái → phải là ổn định
        # trong toolbar NOTE hiện tại.
        toolbar_items = []
        for sel in ['button', '[role="button"]', 'a', 'i', 'span', '.btn', '[class*="icon"]']:
            try:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 800)):
                    el = loc.nth(i)
                    if not el.is_visible(timeout=30):
                        continue
                    box = el.bounding_box()
                    if not box:
                        continue
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    if not (toolbar_min_y <= cy <= toolbar_max_y):
                        continue
                    if not (8 <= box["width"] <= 70 and 8 <= box["height"] <= 70):
                        continue
                    key = (round(box["x"]), round(box["y"]), round(box["width"]), round(box["height"]))
                    if any(k == key for k, _ in toolbar_items):
                        continue
                    toolbar_items.append((key, el))
            except Exception:
                pass

        # Chỉ giữ các icon thực sự gần nhau thành một toolbar.
        items = sorted(toolbar_items, key=lambda z: (z[0][1], z[0][0]))
        if fallback_index is not None and items:
            # Nếu có nhiều lớp con (i/span) cùng một icon, gom theo x gần nhau.
            groups = []
            for key, el in items:
                x = key[0]
                placed = False
                for g in groups:
                    if abs(g[0] - x) <= 12:
                        g[1].append((key, el))
                        placed = True
                        break
                if not placed:
                    groups.append([x, [(key, el)]])
            groups.sort(key=lambda g: g[0])
            if 0 <= fallback_index < len(groups):
                _, members = groups[fallback_index]
                # Ưu tiên phần tử lớn nhất/ở ngoài cùng.
                members.sort(key=lambda z: z[0][2] * z[0][3], reverse=True)
                for _, el in members:
                    try:
                        el.click(timeout=2500, force=True)
                        page.wait_for_timeout(400)
                        self.log(f"Đã click icon '{action_name}' theo vị trí toolbar (icon thứ {fallback_index + 1}).")
                        return
                    except Exception:
                        pass

        raise NoteHrmError(
            f"Không tìm thấy icon '{action_name}'. Tool đã thử title/aria-label/class và nhận diện icon theo toolbar."
        )

    def paste_grid(self, page, tsv):
        """Chọn ô Ngày thực hiện -> mở menu Dán dữ liệu -> dán vào textarea.paste-content.

        Luồng của NOTE HRM ở màn hình Đăng ký là:
            1. Chọn ô dữ liệu Ngày thực hiện của dòng đầu tiên.
            2. Click toolbar Dán dữ liệu.
            3. NOTE mở menu có textarea.paste-content.
            4. Paste dữ liệu Excel vào textarea này.

        Không Ctrl+V trực tiếp vào grid sau khi click toolbar vì ở phiên bản giao diện
        hiện tại, Ctrl+V phải đi vào textarea.paste-content của menu Dán dữ liệu.
        """
        self._check_stop()
        self.log("Dán dữ liệu Excel vào bảng chi tiết...")

        # ------------------------------------------------------------------
        # 1) CHỌN Ô NGÀY THỰC HIỆN TRƯỚC
        # ------------------------------------------------------------------
        # Đóng context-menu/header-menu nếu còn sót lại từ lần render trước.
        try:
            page.evaluate("""
                () => {
                    const ids = ['grid_popup_menu'];
                    ids.forEach(id => {
                        const el = document.getElementById(id);
                        if (el) el.style.display = 'none';
                    });
                    document.querySelectorAll('.grid-context-menu, .grid-column-menu').forEach(el => {
                        try { el.style.display = 'none'; } catch (_) {}
                    });
                }
            """)
        except Exception:
            pass

        cell_selected = False
        try:
            self._click_grid_data_cell_under_header(page, "Ngày thực hiện", row_index=0)
            page.wait_for_timeout(350)

            # Không coi việc gọi cell.click() là thành công nếu NOTE chưa tạo editor.
            # Với cột Ngày thực hiện, editor chuẩn của NOTE là input.ngay_th.
            editor = page.locator('input.grid-input-field.ngay_th').last
            if editor.is_visible(timeout=1200):
                try:
                    editor.focus()
                except Exception:
                    pass
                cell_selected = True
                self.log("Đã chọn ô Ngày thực hiện của dòng đầu tiên và editor ngày đang hiển thị.")
            else:
                raise NoteHrmError("Click ô Ngày thực hiện nhưng NOTE chưa mở editor ngày.")
        except Exception as e:
            self.log(
                f"Cách chọn ô Ngày thực hiện theo DOM chưa xác nhận được editor: "
                f"{type(e).__name__}: {e}; thử click lại trực tiếp theo tọa độ ô dữ liệu..."
            )

        # Fallback: xác định lại đúng cell và click bằng mouse thật.
        if not cell_selected:
            header = self._find_grid_header(page, "Ngày thực hiện")
            if header is None:
                raise NoteHrmError("Không tìm thấy tiêu đề cột 'Ngày thực hiện' để chọn ô dữ liệu.")

            hb = header.bounding_box()
            if not hb:
                raise NoteHrmError("Không lấy được vị trí tiêu đề cột 'Ngày thực hiện'.")

            target = None
            # Chỉ tìm trong đúng table chứa header, tránh dính bảng/popup khác.
            try:
                target_table = header.locator("xpath=ancestor::table[1]")
                rows = target_table.locator("tbody tr")
                if rows.count() > 0:
                    row = rows.nth(0)
                    # Tìm index cột từ chính header rồi lấy td tương ứng.
                    headers = target_table.locator("thead th")
                    col_idx = -1
                    for j in range(headers.count()):
                        txt = (headers.nth(j).inner_text(timeout=200) or "").strip().lower()
                        if "ngày thực hiện" in txt:
                            col_idx = j
                            break
                    if col_idx >= 0:
                        tds = row.locator("td")
                        # tbody td thường có thêm row-header ở đầu; thử cả index trực tiếp
                        # và index + 1 để tương thích renderer của NOTE.
                        for idx in [col_idx, col_idx + 1]:
                            if idx < tds.count():
                                candidate = tds.nth(idx)
                                cb = candidate.bounding_box()
                                if cb and cb["width"] > 0 and cb["height"] > 0:
                                    target = candidate
                                    break
            except Exception:
                target = None

            if target is None:
                raise NoteHrmError("Không xác định được ô dữ liệu 'Ngày thực hiện' dòng 1.")

            cb = target.bounding_box()
            page.mouse.click(cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2)
            page.wait_for_timeout(500)

            editor = page.locator('input.grid-input-field.ngay_th').last
            if not editor.is_visible(timeout=1500):
                raise NoteHrmError("Đã click ô Ngày thực hiện nhưng NOTE không mở editor ngày.")
            try:
                editor.focus()
            except Exception:
                pass
            cell_selected = True
            self.log("Đã chọn ô Ngày thực hiện của dòng đầu tiên và xác nhận editor ngày.")

        if not cell_selected:
            raise NoteHrmError("Không thể xác nhận ô Ngày thực hiện dòng đầu tiên.")

        # ------------------------------------------------------------------
        # 2) CHUẨN BỊ CLIPBOARD SAU KHI Ô ĐÃ ĐƯỢC CHỌN
        # ------------------------------------------------------------------
        try:
            pyperclip.copy(str(tsv))
        except Exception as e:
            raise NoteHrmError(
                f"Không đưa được dữ liệu Excel vào clipboard sau khi chọn ô: {type(e).__name__}: {e}"
            ) from e

        page.wait_for_timeout(150)

        # ------------------------------------------------------------------
        # 3) CLICK ĐÚNG ICON DÁN DỮ LIỆU
        # ------------------------------------------------------------------
        paste_selectors = [
            "#TOOLBAR_idkcv_idkcv2_paste",
            'td.toolbar-paste[tooltip*="Dán dữ liệu"]',
            'td.toolbar-paste',
            '[tooltip="Dán dữ liệu (Sau khi Ctrl+C từ Excel, Bảng dữ liệu)"]',
        ]
        paste_clicked = False
        last_paste_error = None
        for paste_sel in paste_selectors:
            try:
                paste_loc = page.locator(paste_sel).first
                if not paste_loc.is_visible(timeout=500):
                    continue
                box = paste_loc.bounding_box()
                if not box or box["width"] <= 0 or box["height"] <= 0:
                    continue
                try:
                    paste_loc.click(timeout=2500, force=True)
                except Exception:
                    paste_loc.evaluate("el => el.click()")
                page.wait_for_timeout(350)
                paste_clicked = True
                self.log("Đã click icon 'Dán dữ liệu' qua selector DOM toolbar-paste.")
                break
            except Exception as e:
                last_paste_error = e

        if not paste_clicked:
            try:
                self._click_grid_toolbar_action(
                    page,
                    "Dán dữ liệu",
                    aliases=["dán dữ liệu", "paste", "clipboard", "paste data", "dữ liệu"],
                    fallback_index=3,
                )
                paste_clicked = True
            except Exception as e:
                last_paste_error = e

        if not paste_clicked:
            raise NoteHrmError(
                f"Không tìm thấy/click được icon 'Dán dữ liệu': "
                f"{type(last_paste_error).__name__}: {last_paste_error}"
            )

        # ------------------------------------------------------------------
        # 4) NOTE MỞ MENU -> PASTE VÀO textarea.paste-content
        # ------------------------------------------------------------------
        # DOM đã xác nhận từ F12:
        # <li index="0" id="0"><a>...
        #   <textarea class="paste-content" ...></textarea>
        # </a></li>
        paste_area = None
        paste_area_selectors = [
            'textarea.paste-content',
            '#grid_popup_menu textarea.paste-content',
            'li[index="0"] textarea.paste-content',
        ]

        last_area_error = None
        for sel in paste_area_selectors:
            try:
                loc = page.locator(sel).last
                if loc.is_visible(timeout=1200):
                    paste_area = loc
                    break
            except Exception as e:
                last_area_error = e

        if paste_area is None:
            raise NoteHrmError(
                "Đã mở 'Dán dữ liệu' nhưng không tìm thấy textarea.paste-content "
                f"để nhận dữ liệu. {type(last_area_error).__name__}: {last_area_error}"
            )

        try:
            paste_area.click(timeout=2500, force=True)
            page.wait_for_timeout(100)
            # Dữ liệu đã được đưa vào clipboard ở bước 2; Ctrl+V lần này được gửi
            # ĐÚNG vào textarea.paste-content, không phải vào grid.
            page.keyboard.press("Control+V")
            page.wait_for_timeout(700)
        except Exception as e:
            raise NoteHrmError(
                f"Không paste được dữ liệu vào textarea.paste-content: "
                f"{type(e).__name__}: {e}"
            ) from e

        # NOTE thường đóng textarea.paste-content ngay sau khi nhận dữ liệu.
        # Vì vậy KHÔNG được coi textarea rỗng/đã biến mất là lỗi: ở thời điểm
        # kiểm tra, popup có thể đã đóng và dữ liệu đã được đưa vào grid.
        page.wait_for_timeout(1000)
        paste_ok = False
        try:
            if paste_area.is_visible(timeout=300):
                pasted_value = paste_area.input_value(timeout=700)
                paste_ok = bool((pasted_value or '').strip())
        except Exception:
            # Textarea biến mất sau khi NOTE xử lý paste -> đây là trạng thái hợp lệ.
            paste_ok = False

        if not paste_ok:
            # Xác nhận gián tiếp bằng chính bảng chi tiết. Không fill lại textarea
            # vì thao tác đó có thể chạy sau khi NOTE đã đóng popup.
            try:
                grid_rows = page.locator('#TABLE_idkcv_idkcv2 tbody tr')
                if not grid_rows.count():
                    grid_rows = page.locator('table[id*="TABLE_idkcv"] tbody tr')
                expected_rows = max(1, len([ln for ln in str(tsv).splitlines() if ln.strip()]))
                visible_count = 0
                for ri in range(grid_rows.count()):
                    try:
                        if grid_rows.nth(ri).is_visible(timeout=50):
                            visible_count += 1
                    except Exception:
                        pass
                if visible_count >= expected_rows:
                    paste_ok = True
            except Exception:
                pass

        if not paste_ok:
            # Trường hợp NOTE vẫn giữ popup mở nhưng clipboard event chưa hoàn tất,
            # thử lại đúng textarea một lần duy nhất.
            try:
                area = page.locator('textarea.paste-content').last
                if area.is_visible(timeout=500):
                    area.click(force=True)
                    page.keyboard.press("Control+V")
                    page.wait_for_timeout(800)
                    try:
                        paste_ok = bool((area.input_value(timeout=700) or '').strip())
                    except Exception:
                        # Popup đóng = NOTE đã tiếp nhận dữ liệu.
                        paste_ok = True
            except Exception:
                pass

        if not paste_ok:
            raise NoteHrmError(
                "Đã click Dán dữ liệu nhưng chưa xác nhận NOTE tiếp nhận dữ liệu vào bảng chi tiết."
            )

        self.log("Đã paste dữ liệu Excel vào bảng chi tiết.")
        page.wait_for_timeout(1200)


    def _get_grid_rows(self, page):
        """Lấy dòng CHỈ trong bảng chi tiết idkcv, tránh dính popup/menu khác."""
        selectors = [
            '#TABLE_idkcv_idkcv2 tbody tr',
            'table[id*="TABLE_idkcv"] tbody tr',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                visible = []
                for i in range(loc.count()):
                    x = loc.nth(i)
                    if x.is_visible(timeout=100):
                        visible.append(x)
                if visible:
                    return page.locator(sel)
            except Exception:
                pass
        return page.locator('table tbody tr')

    def _registration_grid(self, page):
        """Return the editable detail grid in the new-registration form.

        NOTE reuses TABLE_idkcv_idkcv2 in the list behind the modal. The
        editable grid is identified by its own fields, not by the duplicated id.
        """
        tables = page.locator('table[id="TABLE_idkcv_idkcv2"]')
        for index in reversed(range(tables.count())):
            table = tables.nth(index)
            if (table.is_visible() and
                    table.locator('thead th.ngay_th').count() and
                    table.locator('tbody td.ma_cv input.ma_cv').count()):
                return table
        raise NoteHrmError(
            "Không thấy bảng chi tiết đang nhập (có cột Ngày thực hiện "
            "và ô nhập Mã công việc). Kiểm tra màn hình Thêm."
        )

    def _registration_data_rows(self, page):
        """Lấy CHỈ các dòng dữ liệu của bảng đăng ký, không lấy dòng tiêu đề.

        Dòng tiêu đề nằm trong thead. Dữ liệu nằm trong tbody. Một số bản NOTE
        có thể thêm dòng rỗng, vì vậy chỉ giữ tr nếu có td nhìn thấy.
        """
        table = self._registration_grid(page)
        rows = table.locator('tbody > tr')
        result = []
        for i in range(rows.count()):
            row = rows.nth(i)
            try:
                if not row.is_visible(timeout=150):
                    continue
                tds = row.locator('td')
                visible_td = False
                for j in range(tds.count()):
                    td = tds.nth(j)
                    try:
                        if td.is_visible(timeout=50):
                            b = td.bounding_box()
                            if b and b['width'] > 0 and b['height'] > 0:
                                visible_td = True
                                break
                    except Exception:
                        pass
                if visible_td:
                    result.append(row)
            except Exception:
                pass
        return result

    def _find_registration_cell_by_field(self, page, field_class, row_index_zero):
        """Tìm cell bằng class dữ liệu NOTE, ví dụ ma_cv/ngay_ct/han_ht.

        Đây là cách tương đương thao tác F12 mà người dùng đã xác nhận: vào
        đúng TABLE_idkcv_idkcv2 -> tbody -> dòng dữ liệu thứ N -> td có class
        trường tương ứng. Không dựa vào thứ tự cột nên không bị lệch khi header
        co giãn hoặc có cột ẩn.
        """
        rows = self._registration_data_rows(page)
        if row_index_zero >= len(rows):
            raise NoteHrmError(
                f"Không tìm thấy dòng dữ liệu {row_index_zero + 1} trong bảng TABLE_idkcv_idkcv2."
            )
        row = rows[row_index_zero]
        cells = row.locator(f'td.{field_class}')
        visible = []
        for i in range(cells.count()):
            c = cells.nth(i)
            try:
                if c.is_visible(timeout=100):
                    b = c.bounding_box()
                    if b and b['width'] > 0 and b['height'] > 0:
                        visible.append(c)
            except Exception:
                pass
        if not visible:
            # Fallback chính xác theo class token trong DOM.
            cells = row.locator(f'td[class*=" {field_class} "]')
            for i in range(cells.count()):
                c = cells.nth(i)
                try:
                    b = c.bounding_box()
                    if c.is_visible(timeout=100) and b and b['width'] > 0 and b['height'] > 0:
                        visible.append(c)
                except Exception:
                    pass
        if not visible:
            raise NoteHrmError(
                f"Không tìm thấy ô dữ liệu '{field_class}' ở dòng {row_index_zero + 1} trong bảng TABLE_idkcv_idkcv2."
            )
        cell = visible[0]
        b = cell.bounding_box()
        self.log(
            f"Đã tìm đúng ô '{field_class}' dòng {row_index_zero + 1} trong TABLE_idkcv_idkcv2 "
            f"tại x={int(b['x'])}, y={int(b['y'])}."
        )
        return cell

    def _grid_cell_by_header(self, page, header_text, row_index_zero):
        """Trả về cell đúng cột + dòng.

        Ưu tiên mapping trực tiếp từ tiêu đề -> class field của NOTE, sau đó
        lấy td cùng class ở tbody. Fallback cũ chỉ dùng khi NOTE đổi class.
        """
        mapping = {
            'ngày thực hiện': 'ngay_th',
            'mã công việc': 'ma_cv',
            'tên công việc': 'ten_cv',
            'thời hạn hoàn thành': 'ngay_ht',
            'mô tả công việc': 'ghi_chu',
        }
        target = " ".join(str(header_text).split()).strip().lower()
        if target in mapping:
            try:
                return self._find_registration_cell_by_field(page, mapping[target], row_index_zero)
            except Exception:
                pass

        # Fallback cuối: tìm header trong đúng bảng rồi map theo index.
        table = self._registration_grid(page)
        headers = table.locator('thead th')
        col_idx = -1
        for i in range(headers.count()):
            try:
                txt = ' '.join((headers.nth(i).inner_text(timeout=200) or '').split()).lower()
                if target in txt:
                    col_idx = i
                    break
            except Exception:
                pass
        if col_idx < 0:
            raise NoteHrmError(f"Không tìm thấy tiêu đề cột '{header_text}'.")
        rows = self._registration_data_rows(page)
        if row_index_zero >= len(rows):
            raise NoteHrmError(f"Không tìm thấy dòng {row_index_zero + 1} trong bảng đăng ký.")
        row = rows[row_index_zero]
        cells = row.locator('td')
        # Có row-header ở đầu nên thử col và col+1.
        for idx in (col_idx, col_idx + 1):
            if idx < cells.count():
                c = cells.nth(idx)
                try:
                    if c.is_visible(timeout=200):
                        b = c.bounding_box()
                        if b and b['width'] > 0 and b['height'] > 0:
                            return c
                except Exception:
                    pass
        raise NoteHrmError(f"Không xác định được ô '{header_text}' dòng {row_index_zero + 1}.")

    def _click_code_lookup_in_row(self, page, row_index_zero):
        """Focus the actual editable code field, then click its own magnifier.

        The list behind the form has an identically named table. On the form,
        the icon is an IMG inside td.ma_cv and becomes visible only after focus.
        """
        self._check_stop()
        number = row_index_zero + 1
        grid = self._registration_grid(page)
        rows = grid.locator('tbody > tr')
        if number > rows.count():
            raise NoteHrmError(f"Dòng {number}: bảng chỉ có {rows.count()} dòng.")
        row = rows.nth(row_index_zero)
        marker = row.locator('td.row-header').first.inner_text().strip()
        if marker != str(number):
            raise NoteHrmError(
                f"Dòng {number}: số thứ tự hiển thị là '{marker}', "
                "dừng để tránh chọn nhầm dòng."
            )
        editor = row.locator('td.ma_cv input.ma_cv').first
        icon = row.locator('td.ma_cv img.btn-lookup').first
        if not editor.is_visible():
            raise NoteHrmError(f"Dòng {number}: ô nhập Mã công việc không hiển thị.")
        editor.scroll_into_view_if_needed()
        editor.click()
        if not icon.is_visible(timeout=1500):
            raise NoteHrmError(
                f"Dòng {number}: đã chọn ô Mã công việc nhưng kính lúp "
                "trong chính ô đó không xuất hiện."
            )
        icon.click()
        modal = page.locator('#DIR_idmcv_Lookup')
        deadline = time.monotonic() + 60
        next_notice = time.monotonic() + 15
        while time.monotonic() < deadline:
            self._check_stop()
            if modal.is_visible():
                return
            if time.monotonic() >= next_notice:
                self.log(f"Dòng {number}: server đang mở danh mục công việc; tiếp tục chờ...")
                next_notice += 15
            page.wait_for_timeout(500)
        raise NoteHrmError(
            f"Dòng {number}: sau 60 giây nhấn kính lúp danh mục vẫn chưa mở. "
            "Kiểm tra kết nối hoặc phản hồi của NOTE HRM trước khi chạy lại."
        )

    def _read_popup_candidates(self, page):
        # Đọc text trong dialog/grid hiện tại.
        dialogs = page.locator('[role="dialog"], .modal, .ui-dialog')
        text = ""
        if dialogs.count():
            for i in range(min(dialogs.count(), 5)):
                try:
                    if dialogs.nth(i).is_visible(timeout=300):
                        text += "\n" + dialogs.nth(i).inner_text(timeout=1000)
                except Exception:
                    pass
        if not text:
            text = page.locator("body").inner_text(timeout=3000)
        # Heuristic: split non-empty lines.
        return [x.strip() for x in text.splitlines() if x.strip()]

    def _search_popup(self, page, task_name):
        # Tìm ô tìm kiếm trong popup.
        inputs = page.locator('input:not([type="hidden"])')
        visible = []
        for i in range(inputs.count()):
            try:
                x = inputs.nth(i)
                if x.is_visible(timeout=200):
                    visible.append(x)
            except Exception:
                pass
        if not visible:
            return

        # Chọn input có placeholder/title liên quan tìm kiếm trước.
        chosen = None
        for x in visible:
            attrs = " ".join([
                x.get_attribute("placeholder") or "",
                x.get_attribute("aria-label") or "",
                x.get_attribute("title") or "",
            ]).lower()
            if any(k in attrs for k in ["tìm", "search", "công việc", "mã"]):
                chosen = x
                break
        chosen = chosen or visible[-1]
        chosen.fill(task_name)
        page.wait_for_timeout(700)

    def select_code_for_row(self, page, row_index_zero, task_name):
        self._check_stop()
        self.log(f"Dòng {row_index_zero+1}: tìm mã cho '{task_name}'...")
        self._click_code_lookup_in_row(page, row_index_zero)
        page.wait_for_timeout(600)

        # Popup đã được xác định bằng DOM người dùng cung cấp: #DIR_idmcv_Lookup.
        modal = page.locator('#DIR_idmcv_Lookup')
        if not modal.is_visible(timeout=2500):
            raise NoteHrmError(f"Dòng {row_index_zero+1}: đã chọn ô Mã công việc nhưng danh mục công việc chưa mở.")

        search = modal.locator(
            'input.txt-search-lookup, input[placeholder*="Tìm kiếm"], input[placeholder*="Tìm"]'
        ).filter(visible=True).first
        try:
            search.wait_for(state='visible', timeout=30000)
        except PlaywrightTimeoutError as error:
            raise NoteHrmError(
                f"Dòng {row_index_zero+1}: danh mục đã mở nhưng sau 30 giây "
                "chưa có ô tìm kiếm công việc."
            ) from error
        # Searching a full Excel name can return zero rows even when a
        # related catalogue item exists. Retry against the whole catalogue.
        rows = modal.locator('#TABLE_idmcv_0 tbody tr, table.table-lookup tbody tr')

        def listed():
            # Take one DOM snapshot. A tr.nth(index) locator is evaluated only
            # when clicked; filtering can replace/reorder those rows meanwhile.
            return rows.evaluate_all("""elements => elements.flatMap(row => {
                if (!row.getClientRects().length) return [];
                const code = row.querySelector('td.ma_cv')?.innerText?.trim();
                const name = row.querySelector('td.ten_cv')?.innerText?.trim();
                const detail = row.querySelector('td.cong_viec_ct')?.innerText?.trim() || '';
                return code && name ? [[code, name.replace(/\\s+/g, ' '),
                    detail.replace(/\\s+/g, ' ')]] : [];
            })""")

        full_catalog = listed()
        catalog_deadline = time.monotonic() + 30
        while not full_catalog and time.monotonic() < catalog_deadline:
            self._check_stop()
            page.wait_for_timeout(500)
            full_catalog = listed()
        if not full_catalog:
            raise NoteHrmError(
                f"Dòng {row_index_zero+1}: danh mục đã mở nhưng sau 30 giây "
                "vẫn chưa tải được mã và tên công việc."
            )
        search.fill(task_name)
        page.wait_for_timeout(650)
        visible_rows = listed()
        # The name filter may show related names, but the detail fallback must
        # compare against the full catalogue, not only those filtered rows.
        if not any(norm(row[1]) == norm(task_name) for row in visible_rows):
            search.fill('')
            page.wait_for_timeout(650)
            unfiltered = listed()
            visible_rows = (unfiltered if len(unfiltered) >= len(full_catalog)
                            else full_catalog)
        if not visible_rows:
            raise NoteHrmError(
                f"Dòng {row_index_zero+1}: danh mục công việc không có ứng viên "
                f"cho '{task_name}'."
            )
        try:
            (selected_code, selected, _detail), score, mode = choose_catalog_candidate(
                task_name, visible_rows)
        except ValueError as error:
            raise NoteHrmError(f"Dòng {row_index_zero+1}: {error}") from error
        self.log(f"Dòng {row_index_zero+1}: chọn '{selected}' [{selected_code}] ({mode}, {score:.1f}%).")

        # This NOTE version selects and closes the lookup on a single cell
        # click. Older versions may keep the lookup open until Đồng ý.
        code_cells = modal.locator(
            '#TABLE_idmcv_0 tbody td.ma_cv, table.table-lookup tbody td.ma_cv'
        ).filter(has_text=re.compile(r'^\s*' + re.escape(selected_code) + r'\s*$'))
        def click_selected_code():
            try:
                code_cells.first.wait_for(state='visible', timeout=5000)
                if code_cells.count() != 1:
                    raise NoteHrmError(
                        f"Dòng {row_index_zero+1}: mã {selected_code} xuất hiện "
                        f"{code_cells.count()} lần trong danh mục; không thể chọn an toàn."
                    )
                current_name = ' '.join(code_cells.first.locator(
                    'xpath=..').locator('td.ten_cv').inner_text().split())
                if current_name != selected:
                    raise NoteHrmError(
                        f"Dòng {row_index_zero+1}: tên của mã {selected_code} "
                        f"đã đổi từ '{selected}' thành '{current_name}'."
                    )
                code_cells.first.click(timeout=5000)
            except PlaywrightTimeoutError as error:
                raise NoteHrmError(
                    f"Dòng {row_index_zero+1}: mã {selected_code} của '{selected}' "
                    "không còn hiển thị sau khi danh mục lọc dữ liệu."
                ) from error
            # NOTE often closes this dialog asynchronously after clicking a
            # catalogue cell. Do not press Đồng ý while that close is pending.
            try:
                modal.wait_for(state='hidden', timeout=1200)
            except PlaywrightTimeoutError:
                pass
            if modal.is_visible():
                ok = modal.locator('button.btn-lookupOk, button[btnid="lookupOk"]').first
                if not ok.is_visible(timeout=1000):
                    raise NoteHrmError(
                        f"Dòng {row_index_zero+1}: đã chọn ứng viên nhưng danh mục "
                        "vẫn mở và không có nút Đồng ý."
                    )
                ok.click()

        click_selected_code()
        code_cell = self._registration_grid(page).locator('tbody > tr').nth(
            row_index_zero).locator('td.ma_cv').first
        code_input = code_cell.locator('input.ma_cv').first
        name_input = self._registration_grid(page).locator('tbody > tr').nth(
            row_index_zero).locator('td.ten_cv input.ten_cv').first
        # NOTE closes the lookup immediately, then fills the form grid in a
        # later callback. A fixed 350 ms delay often reads the old empty input.
        self.log(f"Dòng {row_index_zero+1}: chờ NOTE cập nhật mã và tên trong bảng...")
        try:
            expect(code_input).to_have_value(selected_code, timeout=8000)
        except AssertionError as error:
            actual_code = code_input.input_value().strip()
            if actual_code:
                raise NoteHrmError(
                    f"Dòng {row_index_zero+1}: NOTE ghi mã '{actual_code}', "
                    f"khác mã đã chọn '{selected_code}'."
                ) from error
            # NOTE sometimes closes (or keeps) the lookup without committing
            # its selection. Entering the verified code and leaving the field
            # invokes NOTE's own lookup validation and fills name/SPC.
            self.log(f"Dòng {row_index_zero+1}: danh mục chưa ghi mã; "
                     f"xác nhận trực tiếp mã {selected_code} trong ô...")
            if modal.is_visible():
                modal.locator('button[btnid="lookupCancel"]').last.click()
                modal.wait_for(state='hidden', timeout=3000)
            code_input.fill(selected_code)
            code_input.press('Tab')
            try:
                expect(code_input).to_have_value(selected_code, timeout=8000)
            except AssertionError as retry_error:
                raise NoteHrmError(
                    f"Dòng {row_index_zero+1}: mã {selected_code} không được NOTE chấp nhận "
                    "sau khi nhập trực tiếp."
                ) from retry_error
        try:
            expect(name_input).to_have_value(selected, timeout=10000)
            validated_name = self._registration_grid(page).locator('tbody > tr').nth(
                row_index_zero).locator('td.ten_cv2').first
            if validated_name.count():
                expect(validated_name).to_have_text(selected, timeout=10000)
        except AssertionError as error:
            raise NoteHrmError(
                f"Dòng {row_index_zero+1}: mã {selected_code} có trong ô nhưng NOTE "
                f"chưa xác nhận tên công việc '{selected}'."
            ) from error
        code = (code_input.input_value() if code_input.count()
                else code_cell.inner_text()).strip()
        if code != selected_code or modal.is_visible():
            raise NoteHrmError(
                f"Dòng {row_index_zero+1}: mã công việc sau khi chọn là "
                f"'{code}', dự kiến '{selected_code}' (danh mục còn mở: {modal.is_visible()})."
            )
        self.log(f"Dòng {row_index_zero+1}: đã chọn mã {code}.")

    def _set_deadlines_per_row(self, page, row_count, deadline_date):
        """Enter the deadline in every editable detail row; avoid the grid menu."""
        rows = self._registration_grid(page).locator('tbody > tr')
        if rows.count() != row_count:
            raise NoteHrmError(
                f"Bảng có {rows.count()} dòng thay vì {row_count}; "
                "dừng để tránh nhập hạn sai dòng."
            )
        for index in range(row_count):
            self._check_stop()
            row = rows.nth(index)
            number = index + 1
            marker = row.locator('td.row-header').first.inner_text().strip()
            if marker != str(number):
                raise NoteHrmError(
                    f"Dòng {number}: số thứ tự hiển thị là '{marker}'; "
                    "dừng để tránh nhập hạn sai dòng."
                )
            editor = row.locator('td.ngay_ht input.ngay_ht').first
            if not editor.is_visible():
                raise NoteHrmError(f"Dòng {number}: không thấy ô Thời hạn hoàn thành.")
            editor.scroll_into_view_if_needed()
            editor.fill(deadline_date)
            editor.press('Tab')
            try:
                expect(editor).to_have_value(deadline_date, timeout=5000)
            except AssertionError as error:
                value = editor.input_value().strip()
                raise NoteHrmError(
                    f"Dòng {number}: hạn hoàn thành là '{value}', "
                    f"chưa phải {deadline_date}."
                ) from error
            self.log(f"Dòng {number}: đã nhập hạn hoàn thành {deadline_date}.")
        # Verify again after all blur/change handlers have run.
        for index in range(row_count):
            value = rows.nth(index).locator('td.ngay_ht input.ngay_ht').first.input_value().strip()
            if value != deadline_date:
                raise NoteHrmError(
                    f"Dòng {index+1}: hạn hoàn thành là '{value}', "
                    f"chưa phải {deadline_date}."
                )
        self.log(f"Đã xác nhận hạn {deadline_date} cho đủ {row_count} dòng.")

    def fill_descriptions(self, page, jobs):
        """Use NOTE's separate description dialog and confirm each row."""
        for index, job in enumerate(jobs):
            self._check_stop()
            row = self._registration_grid(page).locator('tbody > tr').nth(index)
            cell = row.locator('td.ghi_chu').first
            cell.click()
            editor = page.locator('textarea.input-field.data').filter(visible=True)
            try:
                editor.wait_for(state='visible', timeout=3000)
                editor.fill(job.description)
                dialog = editor.locator('xpath=ancestor::*[@role="dialog"][1]')
                ok = dialog.locator('button:has-text("Đồng ý")').first
                ok.click()
            except Exception as error:
                raise NoteHrmError(
                    f"Dòng {index+1}: không nhập/xác nhận được Mô tả công việc."
                ) from error
            page.wait_for_timeout(250)
            actual = ' '.join(cell.inner_text().split())
            expected = ' '.join(job.description.split())
            if actual != expected:
                raise NoteHrmError(
                    f"Dòng {index+1}: mô tả sau nhập là '{actual[:80]}', "
                    f"khác Excel '{expected[:80]}'."
                )
            self.log(f"Dòng {index+1}: đã xác nhận Mô tả công việc.")

    def set_deadlines(self, page, row_count, deadline_date='30/09/2026'):
        self._set_deadlines_per_row(page, row_count, deadline_date)


    def save(self, page, expected_rows=None):
        self._check_stop()
        self.log("Lưu phiếu...")
        # NOTE renders Lưu as a div with tooltip/xcode, not as a button or a
        # title attribute. Scope to its visible quick toolbar action.
        save_button = page.locator(
            'div.quick-toolbar-item.ok[xcode="ok"][tooltip="Lưu"]'
        ).filter(visible=True)
        if save_button.count() != 1:
            raise NoteHrmError(
                f"Không xác định được duy nhất nút Lưu đang hiển thị "
                f"(tìm thấy {save_button.count()})."
            )
        save_button.click(timeout=5000)
        self.log("Đang chờ NOTE HRM hoàn tất lưu và mở phiếu ở chế độ xem...")

        # NOTE saves asynchronously. The input form and spinner can remain
        # visible for several seconds after the toolbar click.
        dialogs = page.locator('[role="dialog"]')
        notices = page.locator('.toast, .toast-message, .alert, .swal2-popup, '
                               '.modal-message, [role="alert"]')
        send_action = page.locator(
            'div.quick-toolbar-item.send[xcode="send"][tooltip="Gửi xử lý chờ duyệt"]'
        ).filter(visible=True)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            self._check_stop()
            # NOTE may warn that it assigned a new document number.
            for index in range(dialogs.count()):
                dialog = dialogs.nth(index)
                if not dialog.is_visible():
                    continue
                message = dialog.inner_text()
                if 'Số chứng từ đã tồn tại' in message and 'tự tăng' in message:
                    dialog.locator('button:has-text("Đồng ý")').first.click()
                    self.log("NOTE đã tự điều chỉnh số chứng từ trùng.")

            for index in range(notices.count()):
                notice = notices.nth(index)
                if notice.is_visible():
                    message = notice.inner_text().lower()
                    if any(word in message for word in ('lỗi', 'không thể', 'không hợp lệ', 'bắt buộc')):
                        raise NoteHrmError(f"NOTE HRM từ chối lưu: {message[:300]}")

            if not self._registration_grid_is_open(page) and send_action.count() == 1:
                tables = page.locator('table[id="TABLE_idkcv_idkcv2"]')
                for index in range(tables.count()):
                    table = tables.nth(index)
                    if not table.is_visible() or table.locator('tbody input.ma_cv').count():
                        continue
                    rows = table.locator('tbody > tr')
                    if expected_rows is None or rows.count() == expected_rows:
                        self.log(f"Đã lưu và mở phiếu ở chế độ xem ({rows.count()} dòng); "
                                 "đã thấy nút Gửi xử lý.")
                        return
            page.wait_for_timeout(500)
        raise NoteHrmError(
            "Sau 45 giây chưa xác nhận được màn hình xem phiếu có nút Gửi xử lý "
            "và đủ dòng. Kiểm tra phiếu trên NOTE HRM trước khi chạy lại để tránh tạo trùng."
        )

    def _registration_grid_is_open(self, page):
        try:
            self._registration_grid(page)
            return True
        except NoteHrmError:
            return False

    def run_account(self, username, password, excel_path, plan_name, content,
                    start_date='01/07/2026', end_date='30/09/2026',
                    deadline_date='30/09/2026'):
        from excel_reader import load_jobs, validate_run_dates, make_clipboard_tsv
        jobs = load_jobs(excel_path)
        start_date, end_date, deadline_date = validate_run_dates(
            start_date, end_date, deadline_date, [(excel_path, jobs)],
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not self.visible)
            context = browser.new_context(viewport={"width": 1600, "height": 900})
            page = context.new_page()
            try:
                self.log(f"Excel hợp lệ: {len(jobs)} dòng công việc.")
                self.login(page, username, password)
                self.ensure_hrm_module(page)
                self.open_registration(page)
                self.click_add(page)
                self.fill_header(page, plan_name, content, start_date, end_date)
                tsv = make_clipboard_tsv(jobs)
                self.paste_grid(page, tsv)

                # Detect malformed clipboard rows before selecting codes in
                # the wrong grid positions (e.g. an Excel cell has a newline).
                pasted_rows = self._registration_grid(page).locator('tbody > tr')
                try:
                    expect(pasted_rows).to_have_count(len(jobs), timeout=5000)
                except AssertionError as error:
                    raise NoteHrmError(
                        f"Sau khi dán, bảng có {pasted_rows.count()} dòng "
                        f"nhưng Excel có {len(jobs)} công việc. "
                        "Dừng trước khi chọn mã để tránh lệch dòng."
                    ) from error
                self.log(f"Đã đối chiếu số dòng sau khi dán: {len(jobs)} công việc.")

                # Every row must have a selected code before saving.
                for idx, job in enumerate(jobs):
                    self._check_stop()
                    self.select_code_for_row(page, idx, job.task_name)

                self.set_deadlines(page, len(jobs), deadline_date)
                self.fill_descriptions(page, jobs)
                self.save(page, expected_rows=len(jobs))
                # Chỉ chuyển sang tài khoản tiếp theo sau khi xác nhận đăng xuất.
                self.logout(page)
            except Exception as e:
                # Chụp bằng chứng lỗi.
                try:
                    Path("logs").mkdir(exist_ok=True)
                    safe = "".join(ch if ch.isalnum() else "_" for ch in username)[:50]
                    page.screenshot(path=f"logs/error_{safe}.png", full_page=True)
                except Exception:
                    pass
                raise
            finally:
                context.close()
                browser.close()
