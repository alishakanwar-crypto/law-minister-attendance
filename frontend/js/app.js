/**
 * Staff Attendance System — Frontend Application
 * Law Minister's Office
 */

const API = '';

// ---- Utilities ----

function toast(msg, type = 'info') {
    const container = document.getElementById('toastContainer');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

async function api(path, opts = {}) {
    try {
        const resp = await fetch(API + path, opts);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return await resp.json();
    } catch (e) {
        toast(e.message, 'error');
        throw e;
    }
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function formatTime(isoStr) {
    if (!isoStr) return '';
    try {
        const d = new Date(isoStr);
        return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    } catch {
        return isoStr;
    }
}

// ---- Tab Navigation ----

function switchTab(tab) {
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.getElementById(`tab-${tab}`).style.display = 'block';
    document.querySelector(`.nav-item[data-tab="${tab}"]`).classList.add('active');

    if (tab === 'dashboard') refreshDashboard();
    if (tab === 'staff') loadStaff();
    if (tab === 'cameras') loadCameras();
    if (tab === 'attendance') loadAttendanceLog();
    if (tab === 'settings') loadSettings();
}

// ---- Dashboard ----

async function refreshDashboard() {
    try {
        const summary = await api('/api/attendance/summary');
        document.getElementById('statTotal').textContent = summary.total_staff;
        document.getElementById('statPresent').textContent = summary.present;
        document.getElementById('statAbsent').textContent = summary.absent;
        document.getElementById('statPct').textContent = summary.attendance_pct + '%';
    } catch {}

    try {
        const report = await api('/api/attendance/report');
        const tbody = document.getElementById('dashboardTable');
        const empty = document.getElementById('dashboardEmpty');

        if (!report.report || report.report.length === 0) {
            tbody.innerHTML = '';
            empty.style.display = 'block';
            return;
        }
        empty.style.display = 'none';

        tbody.innerHTML = report.report.map(r => `
            <tr>
                <td>${r.staff_id}</td>
                <td>${r.name}</td>
                <td><span class="badge ${r.status === 'Present' ? 'badge-present' : 'badge-absent'}">${r.status}</span></td>
                <td>${formatTime(r.time_in)}</td>
                <td>${r.confidence ? (r.confidence * 100).toFixed(1) + '%' : '—'}</td>
                <td>${r.camera || '—'}</td>
            </tr>
        `).join('');
    } catch {}

    updateEngineStatus();
}

// ---- Engine Control ----

async function updateEngineStatus() {
    try {
        const status = await api('/api/engine/status');
        const dot = document.getElementById('engineDot');
        const label = document.getElementById('engineLabel');
        const btn = document.getElementById('btnStartEngine');

        if (status.running) {
            dot.classList.add('active');
            label.textContent = `Running — ${status.frames_processed} frames`;
            btn.textContent = 'Stop';
            btn.className = 'btn btn-danger btn-sm';
        } else {
            dot.classList.remove('active');
            label.textContent = 'Engine Stopped';
            btn.textContent = 'Start';
            btn.className = 'btn btn-success btn-sm';
        }
    } catch {}
}

async function toggleEngine() {
    const btn = document.getElementById('btnStartEngine');
    const isRunning = btn.textContent === 'Stop';
    try {
        if (isRunning) {
            await api('/api/engine/stop', { method: 'POST' });
            toast('Attendance engine stopped', 'info');
        } else {
            await api('/api/engine/start', { method: 'POST' });
            toast('Attendance engine started', 'success');
        }
        updateEngineStatus();
    } catch {}
}

// ---- Staff Management ----

async function loadStaff() {
    try {
        const data = await api('/api/staff');
        const tbody = document.getElementById('staffTable');
        const empty = document.getElementById('staffEmpty');

        if (!data.staff || data.staff.length === 0) {
            tbody.innerHTML = '';
            empty.style.display = 'block';
            return;
        }
        empty.style.display = 'none';

        tbody.innerHTML = data.staff.map(s => `
            <tr>
                <td><strong>${s.staff_id}</strong></td>
                <td>${s.name}</td>
                <td>${s.designation || '—'}</td>
                <td>${s.department || '—'}</td>
                <td>${s.phone || '—'}</td>
                <td>${s.face_count || 0}</td>
                <td><span class="badge ${s.active ? 'badge-present' : 'badge-absent'}">${s.active ? 'Active' : 'Inactive'}</span></td>
                <td>
                    <button class="btn btn-outline btn-sm" onclick="showAddFaceModal('${s.staff_id}', '${s.name}')">+ Face</button>
                    <button class="btn btn-danger btn-sm" onclick="confirmDeleteStaff('${s.staff_id}')">Delete</button>
                </td>
            </tr>
        `).join('');
    } catch {}
}

function showAddStaffModal() {
    document.getElementById('newStaffId').value = '';
    document.getElementById('newStaffName').value = '';
    document.getElementById('newStaffDesignation').value = '';
    document.getElementById('newStaffDept').value = '';
    document.getElementById('newStaffPhone').value = '';
    document.getElementById('newStaffEmail').value = '';
    document.getElementById('staffPhotoFile').value = '';
    document.getElementById('staffPhotoUpload').innerHTML = '<p>Click to upload a clear face photo</p><input type="file" id="staffPhotoFile" accept="image/*" style="display:none" onchange="previewStaffPhoto(this)">';
    document.getElementById('staffPhotoUpload').classList.remove('has-image');
    openModal('staffModal');
}

function previewStaffPhoto(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const container = document.getElementById('staffPhotoUpload');
            container.innerHTML = `<img src="${e.target.result}" alt="Preview"><p>Click to change photo</p><input type="file" id="staffPhotoFile" accept="image/*" style="display:none" onchange="previewStaffPhoto(this)">`;
            container.classList.add('has-image');
        };
        reader.readAsDataURL(input.files[0]);
    }
}

async function addStaff() {
    const staffId = document.getElementById('newStaffId').value.trim();
    const name = document.getElementById('newStaffName').value.trim();
    const designation = document.getElementById('newStaffDesignation').value.trim();
    const department = document.getElementById('newStaffDept').value.trim();
    const phone = document.getElementById('newStaffPhone').value.trim();
    const email = document.getElementById('newStaffEmail').value.trim();
    const photoFile = document.getElementById('staffPhotoFile').files[0];

    if (!staffId || !name) {
        toast('Staff ID and Name are required', 'error');
        return;
    }

    // Step 1: Create staff record
    const formData = new FormData();
    formData.append('staff_id', staffId);
    formData.append('name', name);
    formData.append('designation', designation);
    formData.append('department', department);
    formData.append('phone', phone);
    formData.append('email', email);

    try {
        await api('/api/staff', { method: 'POST', body: formData });
    } catch {
        return;
    }

    // Step 2: Register face if photo provided
    if (photoFile) {
        const faceForm = new FormData();
        faceForm.append('photo', photoFile);
        faceForm.append('angle', 'front');
        try {
            await api(`/api/staff/${staffId}/face`, { method: 'POST', body: faceForm });
            toast(`${name} registered with face`, 'success');
        } catch {
            toast(`${name} added but face registration failed`, 'error');
        }
    } else {
        toast(`${name} added (no face photo yet)`, 'success');
    }

    closeModal('staffModal');
    loadStaff();
}

async function confirmDeleteStaff(staffId) {
    if (!confirm(`Delete staff ${staffId} and all their face data?`)) return;
    try {
        await api(`/api/staff/${staffId}`, { method: 'DELETE' });
        toast('Staff deleted', 'info');
        loadStaff();
    } catch {}
}

// ---- Face Registration ----

function showAddFaceModal(staffId, name) {
    document.getElementById('faceModalStaffId').textContent = staffId;
    document.getElementById('faceModalStaffName').textContent = name;
    document.getElementById('facePhotoFile').value = '';
    document.getElementById('facePhotoUpload').innerHTML = '<p>Click to upload face photo</p><input type="file" id="facePhotoFile" accept="image/*" style="display:none" onchange="previewFacePhoto(this)">';
    document.getElementById('facePhotoUpload').classList.remove('has-image');
    document.getElementById('faceAngle').value = 'front';
    openModal('faceModal');
}

function previewFacePhoto(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const container = document.getElementById('facePhotoUpload');
            container.innerHTML = `<img src="${e.target.result}" alt="Preview"><p>Click to change photo</p><input type="file" id="facePhotoFile" accept="image/*" style="display:none" onchange="previewFacePhoto(this)">`;
            container.classList.add('has-image');
        };
        reader.readAsDataURL(input.files[0]);
    }
}

async function registerFace() {
    const staffId = document.getElementById('faceModalStaffId').textContent;
    const angle = document.getElementById('faceAngle').value;
    const photoFile = document.getElementById('facePhotoFile').files[0];

    if (!photoFile) {
        toast('Please select a photo', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('photo', photoFile);
    formData.append('angle', angle);

    try {
        await api(`/api/staff/${staffId}/face`, { method: 'POST', body: formData });
        toast('Face registered successfully', 'success');
        closeModal('faceModal');
        loadStaff();
    } catch {}
}

// ---- Camera Management ----

async function loadCameras() {
    try {
        const data = await api('/api/cameras');
        const tbody = document.getElementById('cameraTable');
        const empty = document.getElementById('cameraEmpty');

        if (!data.cameras || data.cameras.length === 0) {
            tbody.innerHTML = '';
            empty.style.display = 'block';
            return;
        }
        empty.style.display = 'none';

        tbody.innerHTML = data.cameras.map(c => `
            <tr>
                <td><strong>${c.name}</strong></td>
                <td>${c.source_type.toUpperCase()}</td>
                <td>${c.source_url || c.ip || '—'}</td>
                <td><span class="badge ${c.active ? 'badge-present' : 'badge-absent'}">${c.active ? 'Active' : 'Disabled'}</span></td>
                <td>
                    <button class="btn btn-outline btn-sm" onclick="testCamera(${c.id})">Test</button>
                    <button class="btn btn-danger btn-sm" onclick="confirmDeleteCamera(${c.id})">Delete</button>
                </td>
            </tr>
        `).join('');
    } catch {}
}

function showAddCameraModal() {
    document.getElementById('newCamName').value = '';
    document.getElementById('newCamType').value = 'rtsp';
    document.getElementById('newCamRtspUrl').value = '';
    document.getElementById('newCamIp').value = '';
    document.getElementById('newCamPort').value = '80';
    document.getElementById('newCamUser').value = 'admin';
    document.getElementById('newCamPass').value = '';
    document.getElementById('newCamChannel').value = '1';
    document.getElementById('newCamDeviceIdx').value = '0';
    document.getElementById('newCamTestUrl').value = '';
    document.getElementById('newCamDesc').value = '';
    toggleCameraFields();
    openModal('cameraModal');
}

function toggleCameraFields() {
    const type = document.getElementById('newCamType').value;
    document.getElementById('camFieldsRtsp').style.display = type === 'rtsp' ? 'block' : 'none';
    document.getElementById('camFieldsHikvision').style.display = type === 'hikvision' ? 'block' : 'none';
    document.getElementById('camFieldsWebcam').style.display = type === 'webcam' ? 'block' : 'none';
    document.getElementById('camFieldsUrl').style.display = type === 'url' ? 'block' : 'none';
}

async function addCamera() {
    const name = document.getElementById('newCamName').value.trim();
    const sourceType = document.getElementById('newCamType').value;

    if (!name) {
        toast('Camera name is required', 'error');
        return;
    }

    const payload = {
        name,
        source_type: sourceType,
        description: document.getElementById('newCamDesc').value.trim(),
    };

    if (sourceType === 'rtsp') {
        payload.source_url = document.getElementById('newCamRtspUrl').value.trim();
    } else if (sourceType === 'hikvision') {
        payload.ip = document.getElementById('newCamIp').value.trim();
        payload.port = parseInt(document.getElementById('newCamPort').value) || 80;
        payload.username = document.getElementById('newCamUser').value.trim();
        payload.password = document.getElementById('newCamPass').value;
        payload.channel = parseInt(document.getElementById('newCamChannel').value) || 1;
    } else if (sourceType === 'webcam') {
        payload.source_url = document.getElementById('newCamDeviceIdx').value;
    } else if (sourceType === 'url') {
        payload.source_url = document.getElementById('newCamTestUrl').value.trim();
    }

    try {
        await api('/api/cameras', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        toast('Camera added', 'success');
        closeModal('cameraModal');
        loadCameras();
    } catch {}
}

async function testCamera(id) {
    toast('Testing camera connection...', 'info');
    try {
        const result = await api(`/api/cameras/${id}/test`, { method: 'POST' });
        if (result.success) {
            toast(`Camera OK — captured ${result.frame_size} bytes`, 'success');
        } else {
            toast(`Camera test failed: ${result.error}`, 'error');
        }
    } catch {}
}

async function confirmDeleteCamera(id) {
    if (!confirm('Delete this camera?')) return;
    try {
        await api(`/api/cameras/${id}`, { method: 'DELETE' });
        toast('Camera deleted', 'info');
        loadCameras();
    } catch {}
}

// ---- Attendance Log ----

async function loadAttendanceLog() {
    const dateInput = document.getElementById('attendanceDate');
    const dateVal = dateInput.value || null;

    try {
        const data = await api(`/api/attendance${dateVal ? '?date=' + dateVal : ''}`);
        const tbody = document.getElementById('attendanceLogTable');

        if (!data.attendance || data.attendance.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:30px;">No records for this date</td></tr>';
            return;
        }

        tbody.innerHTML = data.attendance.map(r => `
            <tr>
                <td>${r.staff_id}</td>
                <td>${r.name}</td>
                <td><span class="badge badge-present">${r.status}</span></td>
                <td>${formatTime(r.logged_at)}</td>
                <td>${(r.confidence * 100).toFixed(1)}%</td>
                <td>${r.camera_source || '—'}</td>
            </tr>
        `).join('');
    } catch {}
}

async function exportAttendance() {
    const dateVal = document.getElementById('attendanceDate').value || null;
    try {
        const data = await api(`/api/export/attendance${dateVal ? '?date=' + dateVal : ''}`);
        const blob = new Blob([data.csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = data.filename;
        a.click();
        URL.revokeObjectURL(url);
        toast('CSV exported', 'success');
    } catch {}
}

// ---- Reports ----

async function loadReport() {
    const dateVal = document.getElementById('reportDate').value || null;
    try {
        const data = await api(`/api/attendance/report${dateVal ? '?date=' + dateVal : ''}`);
        const tbody = document.getElementById('reportTable');

        if (!data.report || data.report.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:30px;">No data</td></tr>';
            return;
        }

        tbody.innerHTML = data.report.map(r => `
            <tr>
                <td>${r.staff_id}</td>
                <td>${r.name}</td>
                <td>${r.designation || '—'}</td>
                <td>${r.department || '—'}</td>
                <td><span class="badge ${r.status === 'Present' ? 'badge-present' : 'badge-absent'}">${r.status}</span></td>
                <td>${formatTime(r.time_in)}</td>
            </tr>
        `).join('');
    } catch {}
}

// ---- Manual Check-in ----

async function manualCheckin() {
    const fileInput = document.getElementById('manualCheckinFile');
    if (!fileInput.files[0]) {
        toast('Select a photo first', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('photo', fileInput.files[0]);

    const resultDiv = document.getElementById('manualCheckinResult');
    resultDiv.innerHTML = '<p style="color:var(--text-secondary)">Processing...</p>';

    try {
        const data = await api('/api/attendance/manual-checkin', {
            method: 'POST',
            body: formData,
        });

        if (data.records && data.records.length > 0) {
            resultDiv.innerHTML = data.records.map(r =>
                `<p style="color:var(--success);font-weight:600;">
                    Matched: ${r.name} (${r.staff_id}) — ${(r.confidence * 100).toFixed(1)}% confidence
                </p>`
            ).join('');
            refreshDashboard();
        } else {
            resultDiv.innerHTML = '<p style="color:var(--danger);">No registered face matched in this photo.</p>';
        }
    } catch {
        resultDiv.innerHTML = '<p style="color:var(--danger);">Processing failed.</p>';
    }
}

// ---- Settings ----

async function loadSettings() {
    try {
        const cfg = await api('/api/settings');
        document.getElementById('settOfficeName').value = cfg.office_name || '';
        const startH = String(cfg.attendance_start_hour || 9).padStart(2, '0');
        const startM = String(cfg.attendance_start_minute || 0).padStart(2, '0');
        document.getElementById('settStartTime').value = `${startH}:${startM}`;
        const endH = String(cfg.attendance_end_hour || 11).padStart(2, '0');
        const endM = String(cfg.attendance_end_minute || 0).padStart(2, '0');
        document.getElementById('settEndTime').value = `${endH}:${endM}`;
        document.getElementById('settThreshold').value = cfg.recognition_threshold || 0.45;
        document.getElementById('settCooldown').value = cfg.cooldown_seconds || 300;
        document.getElementById('settInterval').value = cfg.snapshot_interval_seconds || 5;
    } catch {}
}

async function saveSettings() {
    const startTime = document.getElementById('settStartTime').value.split(':');
    const endTime = document.getElementById('settEndTime').value.split(':');

    const payload = {
        office_name: document.getElementById('settOfficeName').value,
        attendance_start_hour: parseInt(startTime[0]) || 9,
        attendance_start_minute: parseInt(startTime[1]) || 0,
        attendance_end_hour: parseInt(endTime[0]) || 11,
        attendance_end_minute: parseInt(endTime[1]) || 0,
        recognition_threshold: parseFloat(document.getElementById('settThreshold').value) || 0.45,
        cooldown_seconds: parseInt(document.getElementById('settCooldown').value) || 300,
        snapshot_interval_seconds: parseInt(document.getElementById('settInterval').value) || 5,
    };

    try {
        await api('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        toast('Settings saved', 'success');
    } catch {}
}

// ---- Auto-refresh ----

let refreshInterval = null;

function startAutoRefresh() {
    refreshInterval = setInterval(() => {
        const activeTab = document.querySelector('.nav-item.active');
        if (activeTab && activeTab.dataset.tab === 'dashboard') {
            refreshDashboard();
        }
    }, 15000);
}

// ---- Init ----

document.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
    startAutoRefresh();
    document.getElementById('attendanceDate').valueAsDate = new Date();
    document.getElementById('reportDate').valueAsDate = new Date();
});
