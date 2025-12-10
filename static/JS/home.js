// Cấu hình API
const API_BASE_URL = '/api';
let currentAnalysisResult = null; // Biến lưu kết quả để xuất báo cáo

// --- 1. KHỞI TẠO (CHẠY KHI WEB LOAD XONG) ---
document.addEventListener('DOMContentLoaded', function () {
    console.log("Website đã tải xong. Đang khởi tạo...");

    // Gán sự kiện cho input file
    const fileInput = document.getElementById('file-upload');
    if (fileInput) {
        // Hủy sự kiện cũ (nếu có) để tránh lặp
        fileInput.removeEventListener('change', handleFileUpload);
        fileInput.addEventListener('change', handleFileUpload);
        console.log("Đã kích hoạt tính năng Upload File.");
    } else {
        console.error("Lỗi: Không tìm thấy thẻ input có id='file-upload'!");
    }
});

// --- 2. XỬ LÝ UPLOAD FILE (ĐỌC FILE VÀO Ô TEXTAREA) ---
function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    console.log("Đang đọc file:", file.name);

    // Kiểm tra dung lượng (giới hạn 5MB)
    if (file.size > 5 * 1024 * 1024) {
        alert("File quá lớn (Max 5MB)!");
        return;
    }

    // Đọc nội dung file
    const reader = new FileReader();
    reader.onload = function(e) {
        const content = e.target.result;
        // Điền code vào ô nhập liệu
        document.getElementById('code-input').value = content;

        // Cập nhật trạng thái
        updateStatus(`Đã tải file: ${file.name}`, "#4f46e5");

        // Tự động cuộn xuống
        document.getElementById('code-input').focus();
    };

    reader.onerror = function() {
        alert("Lỗi khi đọc file!");
    };

    reader.readAsText(file);

    // Reset input để chọn lại file trùng tên vẫn được
    event.target.value = '';
}

// --- 3. GỌI AI PHÂN TÍCH ---
async function analyzeCode() {
    const code = document.getElementById('code-input').value.trim();

    if (!code) {
        alert("Vui lòng nhập code hoặc upload file trước!");
        return;
    }

    // Hiển thị loading
    showLoader();
    updateStatus("Đang gửi code tới AI...", "#e67e22");

    try {
        const response = await fetch(`${API_BASE_URL}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code })
        });

        const data = await response.json();

        if (data.error) {
            showError(data.error);
            return;
        }

        // LƯU KẾT QUẢ VÀO BIẾN TOÀN CỤC (ĐỂ XUẤT BÁO CÁO)
        currentAnalysisResult = data;

        // HIỂN THỊ KẾT QUẢ
        renderResults(data);
        updateStatus("Phân tích thành công!", "#10b981");

    } catch (err) {
        console.error(err);
        showError("Lỗi kết nối Server! Kiểm tra lại terminal Python.");
    }
}

// --- 4. HIỂN THỊ KẾT QUẢ VÀ NÚT BÁO CÁO ---
function renderResults(data) {
    // Cập nhật thống kê header
    const bugs = data.risks ? data.risks.length : 0;
    document.getElementById('stat-score').innerText = (data.score || 0) + "/100";
    document.getElementById('stat-security').innerText = data.security_issues || 0;
    document.getElementById('stat-bugs').innerText = bugs;

    // Vẽ HTML chi tiết
    let html = '';

    // A. Tóm tắt
    html += `
        <div class="ai-result-card">
            <strong><i class="fa-solid fa-robot"></i> Đánh giá AI:</strong>
            <p>${data.summary || "Không có nội dung."}</p>
        </div>
    `;

    // B. Chi tiết lỗi
    if (data.risks && data.risks.length > 0) {
        html += `<h4><i class="fa-solid fa-triangle-exclamation"></i> Vấn đề cần sửa:</h4>`;
        data.risks.forEach(risk => {
            // Đổi màu theo loại lỗi
            let cssClass = 'ai-risk'; // Đỏ (Mặc định)
            const cat = (risk.category || "").toLowerCase();
            if (cat.includes('syntax') || cat.includes('pep8')) cssClass = 'ai-style'; // Vàng
            if (cat.includes('performance')) cssClass = 'ai-perf'; // Xanh

            html += `
                <div class="ai-result-card ${cssClass}">
                    <strong>[${risk.category || 'Warning'}]</strong> ${risk.msg}
                </div>`;
        });
    } else {
        html += `<div style="color:#10b981; margin: 15px 0;"><i class="fa-solid fa-check-circle"></i> Code sạch, không tìm thấy lỗi nghiêm trọng.</div>`;
    }

    // C. Code Refactor
    if (data.suggested_fix) {
        html += `
            <div class="ai-result-card ai-suggestion">
                <strong><i class="fa-solid fa-wand-magic-sparkles"></i> Code Đề Xuất (Refactor):</strong>
                <pre>${escapeHtml(data.suggested_fix)}</pre>
            </div>
        `;
    }

    // D. NÚT XUẤT BÁO CÁO (ĐÂY LÀ PHẦN BẠN CẦN)
    // Nút này sẽ được chèn vào cuối bảng kết quả
    html += `
        <div style="margin-top: 30px; padding-top: 20px; border-top: 2px dashed #e5e7eb;">
            <div style="display: flex; gap: 15px; justify-content: flex-end; align-items: center;">
                <span style="font-size: 13px; color: #6b7280; font-style: italic;">
                    * Tải báo cáo chi tiết về máy:
                </span>
                <button onclick="exportReport('pdf')" class="btn-primary" style="background-color: #ef4444;">
                    <i class="fa-solid fa-file-pdf"></i> Xuất PDF
                </button>
                <button onclick="exportReport('html')" class="btn-primary" style="background-color: #3b82f6;">
                    <i class="fa-solid fa-file-code"></i> Xuất HTML
                </button>
            </div>
        </div>
    `;

    document.getElementById('output-container').innerHTML = html;
}

// --- 5. HÀM XUẤT BÁO CÁO ---
async function exportReport(type) {
    if (!currentAnalysisResult) {
        alert("Chưa có kết quả phân tích!");
        return;
    }

    const endpoint = type === 'pdf' ? '/api/export/pdf' : '/api/export/html';

    // Đổi icon nút bấm để báo đang tải
    const btn = event.currentTarget;
    const oldHtml = btn.innerHTML;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Đang tạo...`;
    btn.disabled = true;

    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(currentAnalysisResult)
        });

        if (!res.ok) throw new Error("Server báo lỗi khi tạo file.");

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `Report_Review_${Date.now()}.${type}`;
        document.body.appendChild(a);
        a.click();
        a.remove();

    } catch (e) {
        alert("Lỗi xuất báo cáo: " + e.message);
    } finally {
        btn.innerHTML = oldHtml;
        btn.disabled = false;
    }
}

// --- TIỆN ÍCH ---
function clearCode() {
    document.getElementById('code-input').value = '';
    document.getElementById('output-container').innerHTML = `
        <div id="view-empty" class="view-state">
            <div class="empty-img"><i class="fa-solid fa-code-branch"></i></div>
            <p>Sẵn sàng phân tích</p>
        </div>`;
    currentAnalysisResult = null;
    updateStatus("Sẵn sàng", "#6b7280");
}

function showLoader() {
    document.getElementById('output-container').innerHTML = `
        <div style="padding: 50px; text-align: center;">
            <i class="fa-solid fa-spinner fa-spin fa-3x" style="color: #4f46e5;"></i>
            <p style="margin-top: 15px; color: #6b7280;">AI đang suy nghĩ...</p>
        </div>
    `;
}

function updateStatus(msg, color) {
    const el = document.getElementById('status-text');
    if(el) { el.innerText = msg; el.style.color = color; }
}

function showError(msg) {
    document.getElementById('output-container').innerHTML = `
        <div style="color: #dc2626; background: #fee2e2; padding: 20px; border-radius: 8px; text-align: center;">
            <i class="fa-solid fa-triangle-exclamation fa-2x"></i>
            <p style="margin-top: 10px;">${msg}</p>
        </div>
    `;
    updateStatus("Lỗi", "#dc2626");
}

function escapeHtml(text) {
    if (!text) return "";
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}