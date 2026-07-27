"""Streamlit CSS styles."""

PAGE_STYLE = """
<style>
    .block-container { padding-top: 2rem; }
    .step-label {
        font-size: 0.85rem;
        font-weight: 600;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.25rem;
    }
    .file-stat {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 0.5rem;
        padding: 1rem 1.25rem;
    }
    .file-stat-label {
        font-size: 0.8rem;
        color: #64748b;
        margin-bottom: 0.15rem;
    }
    .file-stat-value {
        font-size: 1.1rem;
        font-weight: 600;
        color: #0f172a;
    }
    .readiness-ready { color: #15803d; font-weight: 700; }
    .readiness-warn { color: #b45309; font-weight: 700; }
    .readiness-not-ready { color: #b91c1c; font-weight: 700; }
    .prep-task-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 0.5rem;
        padding: 0.875rem 1rem;
        min-height: 5.5rem;
        pointer-events: none;
    }
    .prep-task-card-selected {
        border-color: #2563eb;
        background: #eff6ff;
        box-shadow: 0 0 0 1px #2563eb;
    }
    .prep-task-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: #0f172a;
        line-height: 1.35;
        margin-bottom: 0.35rem;
    }
    .prep-task-desc {
        font-size: 0.78rem;
        color: #64748b;
        line-height: 1.45;
    }
    div.element-container:has(.prep-task-card) + div.element-container {
        position: relative;
        z-index: 2;
        margin-top: -5.75rem;
        margin-bottom: 0;
        height: 5.75rem;
    }
    div.element-container:has(.prep-task-card) + div.element-container button {
        height: 5.75rem;
        opacity: 0;
        color: transparent;
        font-size: 0;
        cursor: pointer;
        border: none;
        background: transparent;
    }
    div.element-container:has(.prep-task-card) + div.element-container button:hover {
        opacity: 0;
    }
    div.element-container:has(.prep-task-card) + div.element-container button:focus {
        opacity: 0;
        box-shadow: none;
    }
    .upload-summary-stat {
        background: #ffffff;
        border: 1px solid #dce4ef;
        border-radius: 0.75rem;
        padding: 0.85rem 1rem;
        text-align: center;
        min-height: 5.5rem;
    }
    .upload-summary-icon {
        font-size: 1.25rem;
        margin-bottom: 0.25rem;
    }
    .upload-summary-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: #00205B;
    }
    .upload-summary-label {
        font-size: 0.78rem;
        color: #004B93;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .upload-next-action {
        background: linear-gradient(135deg, #004B93 0%, #009FE3 100%);
        color: #ffffff;
        border-radius: 0.75rem;
        padding: 1rem 1.25rem;
        margin: 0.75rem 0 1rem;
    }
    .upload-next-action-headline {
        font-size: 1.15rem;
        font-weight: 700;
        margin-bottom: 0.35rem;
    }
    .upload-next-action-why {
        font-size: 0.9rem;
        line-height: 1.45;
        opacity: 0.95;
    }
    .upload-next-action-micro {
        font-size: 0.82rem;
        margin-top: 0.45rem;
        font-style: italic;
        opacity: 0.9;
    }
    .upload-order-card {
        background: #ffffff;
        border: 1px solid #dce4ef;
        border-radius: 0.75rem;
        padding: 0.25rem 0 0.5rem;
    }
    .upload-order-card-meta {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
        gap: 0.75rem;
    }
    .upload-order-card-label {
        display: block;
        font-size: 0.75rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 0.15rem;
    }
    .upload-order-arrow {
        text-align: center;
        color: #009FE3;
        font-size: 1.35rem;
        font-weight: 700;
        margin: 0.15rem 0;
    }
    .upload-status-badge {
        border-radius: 0.65rem;
        padding: 0.65rem 0.85rem;
        margin: 0.5rem 0;
        border: 1px solid transparent;
    }
    .upload-status-icon {
        font-size: 1rem;
        margin-right: 0.35rem;
    }
    .upload-status-label {
        font-weight: 700;
        margin-right: 0.35rem;
    }
    .upload-status-explanation {
        font-size: 0.82rem;
        display: block;
        margin-top: 0.2rem;
    }
    .upload-status-extra {
        font-size: 0.82rem;
        margin-top: 0.25rem;
        font-weight: 600;
    }
    .upload-status-uploaded {
        background: #edf8f1;
        border-color: #2E8B57;
        color: #1f5f3f;
    }
    .upload-status-ready {
        background: #e8f6fd;
        border-color: #009FE3;
        color: #004B93;
    }
    .upload-status-needs-confirmation {
        background: #fff8e6;
        border-color: #F4B400;
        color: #7a5b00;
    }
    .upload-status-blocked {
        background: #fdecee;
        border-color: #E32934;
        color: #8b1a22;
    }
    .upload-status-not-started {
        background: #F5F7FA;
        border-color: #cbd5e1;
        color: #475569;
    }
    .upload-status-included {
        background: #e8f0fa;
        border-color: #004B93;
        color: #00205B;
    }
    .metadata-card {
        background: #ffffff;
        border: 1px solid #dce4ef;
        border-radius: 0.75rem;
        padding: 1.25rem 1.5rem;
        margin-bottom: 0.75rem;
    }
    .metadata-status-badge {
        border-radius: 0.65rem;
        padding: 0.75rem 1rem;
        margin-bottom: 0.75rem;
        border: 1px solid transparent;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .metadata-status-icon {
        font-size: 1.1rem;
        flex-shrink: 0;
    }
    .metadata-status-label {
        font-weight: 700;
        font-size: 0.95rem;
    }
    .metadata-status-connected {
        background: #edf8f1;
        border-color: #2E8B57;
        color: #1f5f3f;
    }
    .metadata-status-disconnected {
        background: #fff8e6;
        border-color: #F4B400;
        color: #7a5b00;
    }
    .metadata-last-updated {
        font-size: 0.9rem;
        color: #004B93;
        margin: 0 0 1rem 0;
    }
    .metadata-not-connected-msg {
        font-size: 0.9rem;
        color: #475569;
        line-height: 1.45;
        margin: 0 0 1rem 0;
    }
    .metadata-caption {
        font-size: 0.82rem;
        color: #64748b;
        line-height: 1.45;
        margin: 0.75rem 0 0 0;
        font-style: italic;
    }
    .prep-action-card {
        background: #ffffff;
        border: 1px solid #dce4ef;
        border-left: 4px solid #004B93;
        border-radius: 0.75rem;
        padding: 1rem 1.25rem;
        margin-bottom: 0.5rem;
    }
    .prep-action-card-applied {
        border-left-color: #2E8B57;
        background: #edf8f1;
    }
    .prep-action-card-title {
        font-size: 1rem;
        font-weight: 700;
        color: #00205B;
        margin-bottom: 0.35rem;
    }
    .prep-action-card-desc {
        font-size: 0.9rem;
        color: #475569;
        line-height: 1.45;
        margin-bottom: 0;
    }
</style>
"""
