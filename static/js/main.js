document.addEventListener("DOMContentLoaded", () => {
  initAdminSidebarScrollPersistence();
  initZootiqueAdminSoftNav();

  const isSuperAdmin = document.body.classList.contains("superadmin");
  if (!isSuperAdmin) return;

  initSuperAdminExports();
  initSuperAdminLineCharts();
  initSuperAdminDonuts();
  initSuperAdminFeedback();
  initSuperAdminTabs();
  initSuperAdminSettingsTabs();
});

function initAdminSidebarScrollPersistence() {
  const sidebarNav = document.querySelector(".sidebar-nav");
  if (!sidebarNav) return;

  const isAdminLayout = document.querySelector(".app-container") && document.querySelector(".sidebar");
  if (!isAdminLayout) return;

  const blueprint = document.body.classList.contains("superadmin")
    ? "zootique_admin"
    : (document.body.getAttribute("data-blueprint") || "admin");

  const storageKey = `zootique:sidebarScroll:${blueprint}`;

  function save() {
    try {
      localStorage.setItem(storageKey, String(sidebarNav.scrollTop || 0));
    } catch {
      // ignore
    }
  }

  function restore() {
    let restored = false;
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw != null) {
        const value = Number(raw);
        if (Number.isFinite(value)) {
          sidebarNav.scrollTop = value;
          restored = true;
        }
      }
    } catch {
      // ignore
    }

    if (!restored) {
      const active = sidebarNav.querySelector(".nav-item.active");
      if (active && typeof active.scrollIntoView === "function") {
        active.scrollIntoView({ block: "nearest" });
      }
    }
  }

  restore();

  // Persist on nav clicks (covers normal navigation)
  sidebarNav.addEventListener(
    "click",
    (e) => {
      const anchor = e.target && e.target.closest ? e.target.closest("a") : null;
      if (!anchor) return;

      // Respect new-tab and modifier clicks
      if (e.button === 1 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      save();
    },
    { capture: true }
  );

  // Persist on unload as a fallback
  window.addEventListener("beforeunload", save);
}

function initZootiqueAdminSoftNav() {
  if (!document.body.classList.contains("superadmin")) return;

  const sidebarNav = document.querySelector(".sidebar-nav");
  const contentBody = document.querySelector(".content-body");
  if (!sidebarNav || !contentBody) return;

  const softNavLinks = Array.from(sidebarNav.querySelectorAll('a[data-sa-soft-nav="subscriptions"]'));
  if (!softNavLinks.length) return;

  async function loadSoftNav(url, pushHistory = true) {
    const target = new URL(url, window.location.origin);
    target.searchParams.set("partial", "1");

    const response = await fetch(target.toString(), {
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`Failed to load ${target.pathname}`);

    const html = await response.text();
    contentBody.innerHTML = html;
    if (pushHistory) {
      window.history.pushState({}, "", url);
    }
    window.scrollTo({ top: 0, behavior: "auto" });

    softNavLinks.forEach((link) => link.classList.remove("active"));
    const activeLink = softNavLinks.find((link) => link.href === url || link.href === target.origin + target.pathname);
    if (activeLink) activeLink.classList.add("active");
  }

  sidebarNav.addEventListener("click", (event) => {
    const link = event.target && event.target.closest ? event.target.closest('a[data-sa-soft-nav="subscriptions"]') : null;
    if (!link) return;
    if (event.button === 1 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    event.preventDefault();
    loadSoftNav(link.href).catch(() => {
      window.location.href = link.href;
    });
  });

  window.addEventListener("popstate", () => {
    const current = window.location.pathname;
    const activeLink = softNavLinks.find((link) => {
      const linkUrl = new URL(link.href);
      return linkUrl.pathname === current;
    });
    if (activeLink) {
      loadSoftNav(activeLink.href, false).catch(() => {
        window.location.reload();
      });
    }
  });
}

function getSuperAdminStore() {
  window.ZootiqueSuperAdmin = window.ZootiqueSuperAdmin || {};
  return window.ZootiqueSuperAdmin;
}

function initSuperAdminExports() {
  const store = getSuperAdminStore();
  const mostActive = Array.isArray(store.dashboardMostActive) ? store.dashboardMostActive : [];
  const pdfBtn = document.querySelector('[data-export="pdf"]');
  if (pdfBtn) {
    pdfBtn.addEventListener("click", () => {
      window.print();
    });
  }

  const csvBtn = document.querySelector('[data-export="csv"]');
  if (!csvBtn) return;

  csvBtn.addEventListener("click", () => {
    const rows = [["Zoo Name", "Bookings", "Visitors"]];
    if (mostActive.length) {
      mostActive.forEach((row) => {
        rows.push([
          row.zoo_name || "—",
          String(toNumber(row.booking_count)),
          String(toNumber(row.visitor_count)),
        ]);
      });
    } else {
      rows.push(["No activity data", "0", "0"]);
    }
    const csv = rows
      .map((r) => r.map((v) => '"' + String(v).replaceAll('"', '""') + '"').join(","))
      .join("\n");
    downloadTextFile(csv, "zootique-dashboard-most-active-zoos.csv", "text/csv");
  });
}

function initSuperAdminLineCharts() {
  const store = getSuperAdminStore();
  const containers = document.querySelectorAll("[data-sa-line]");
  if (!containers.length) return;

  containers.forEach((container) => {
    const kind = container.getAttribute("data-sa-line");
    if (kind !== "registrations") return;

    const series = Array.isArray(store.registrations) ? store.registrations : [];
    const labels = series.length
      ? series.map((item) => String(item.label || "—").toUpperCase())
      : ["JAN", "FEB", "MAR", "APR", "MAY", "JUN"];
    const values = series.length ? series.map((item) => toNumber(item.count)) : [0, 0, 0, 0, 0, 0];
    renderLineChartSvg(container, labels, values);
  });
}

function initSuperAdminFeedback() {
  const cards = Array.from(document.querySelectorAll(".sa-feedback-card"));
  if (!cards.length) return;

  const zooEl = document.getElementById("sa_feedback_zoo");
  const timeEl = document.getElementById("sa_feedback_time");
  const starsEl = document.getElementById("sa_feedback_stars");
  const statusEl = document.getElementById("sa_feedback_status");
  const categoryEl = document.getElementById("sa_feedback_category");
  const commentEl = document.getElementById("sa_feedback_comment");
  const replyForm = document.getElementById("sa_reply_form");
  const deleteForm = document.getElementById("sa_delete_form");
  const existingReplyBox = document.getElementById("sa_existing_reply_box");
  const existingReplyText = document.getElementById("sa_existing_reply_text");
  const existingReplyDate = document.getElementById("sa_existing_reply_date");
  const replyHeader = document.getElementById("sa_reply_header");
  const replySubmitBtn = document.getElementById("sa_reply_submit_btn");

  function selectCard(card, shouldScroll = false) {
    cards.forEach((c) => {
      c.classList.remove("is-active");
      c.style.borderColor = "var(--border-light, #e2e8f0)";
      c.style.boxShadow = "none";
    });
    card.classList.add("is-active");
    card.style.borderColor = "var(--primary, #1a4f32)";
    card.style.boxShadow = "0 0 0 1.5px var(--primary, #1a4f32)";

    const zooName = card.getAttribute("data-zoo-name") || "—";
    const category = card.getAttribute("data-category") || "General";
    const createdAt = card.getAttribute("data-created-at") || "—";
    const status = card.getAttribute("data-status") || "—";
    const rating = parseInt(card.getAttribute("data-rating") || "0", 10);
    const comment = card.getAttribute("data-comment") || "";
    const feedbackId = card.getAttribute("data-feedback-id") || "";
    const latestReply = card.getAttribute("data-latest-reply") || "";
    const latestReplyDate = card.getAttribute("data-latest-reply-date") || "";

    if (zooEl) zooEl.textContent = zooName;
    if (categoryEl) categoryEl.textContent = category;
    if (timeEl) timeEl.textContent = `Submitted on ${createdAt} • Category: ${category}`;

    if (starsEl) {
      let starsHtml = "";
      for (let i = 0; i < rating; i++) starsHtml += '<i class="fa-solid fa-star"></i> ';
      for (let i = rating; i < 5; i++) starsHtml += '<i class="fa-regular fa-star" style="color:#cbd5e1;"></i> ';
      starsHtml += ` <strong style="color:var(--text, #0f172a); font-size:12px; margin-left:4px;">${rating}/5 Stars</strong>`;
      starsEl.innerHTML = starsHtml;
    }

    if (commentEl) commentEl.textContent = comment || "—";

    if (statusEl) {
      statusEl.textContent = status;
      if (status === "REPLIED") {
        statusEl.style.background = "#dcfce7";
        statusEl.style.color = "#166534";
      } else if (status === "PENDING") {
        statusEl.style.background = "#fef3c7";
        statusEl.style.color = "#92400e";
      } else {
        statusEl.style.background = "var(--border-light, #e2e8f0)";
        statusEl.style.color = "var(--text-muted, #64748b)";
      }
    }

    if (existingReplyBox && existingReplyText) {
      if (latestReply) {
        existingReplyBox.style.display = "block";
        existingReplyText.textContent = latestReply;
        if (existingReplyDate) {
          existingReplyDate.textContent = `Replied by Super Admin on ${latestReplyDate || createdAt}`;
        }
        if (replyHeader) replyHeader.textContent = "Send Follow-up Reply";
        if (replySubmitBtn) replySubmitBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> SEND ANOTHER REPLY';
      } else {
        existingReplyBox.style.display = "none";
        if (replyHeader) replyHeader.textContent = "Send Reply";
        if (replySubmitBtn) replySubmitBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> SEND REPLY';
      }
    }

    if (replyForm) {
      const template = (window.ZootiqueSuperAdmin && window.ZootiqueSuperAdmin.replyUrlTemplate) || "";
      if (template && feedbackId) {
        replyForm.action = template.replace(/\/0(\/|$)/, `/${feedbackId}$1`);
      }
    }

    if (deleteForm) {
      const template = (window.ZootiqueSuperAdmin && window.ZootiqueSuperAdmin.deleteUrlTemplate) || "";
      if (template && feedbackId) {
        deleteForm.action = template.replace(/\/0(\/|$)/, `/${feedbackId}$1`);
      }
    }

    if (shouldScroll && window.innerWidth <= 900) {
      const panel = document.getElementById("sa_feedback_detail_panel");
      if (panel) {
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }

  cards.forEach((card) => {
    card.addEventListener("click", () => selectCard(card, true));
  });

  // Auto-select the first card
  selectCard(cards[0], false);
}

function initSuperAdminTabs() {
  const tabButtons = Array.from(document.querySelectorAll("[data-sa-tab]"));
  const tabPanels = Array.from(document.querySelectorAll("[data-sa-panel]"));
  if (!tabButtons.length || !tabPanels.length) return;

  function setActive(tabName) {
    tabButtons.forEach((b) => {
      const active = b.getAttribute("data-sa-tab") === tabName;
      b.classList.toggle("is-active", active);
    });
    tabPanels.forEach((p) => {
      const show = p.getAttribute("data-sa-panel") === tabName;
      p.style.display = show ? "block" : "none";
    });
  }

  tabButtons.forEach((b) => {
    b.addEventListener("click", () => setActive(b.getAttribute("data-sa-tab")));
  });

  setActive(tabButtons[0].getAttribute("data-sa-tab"));
}

function initSuperAdminDonuts() {
  const store = getSuperAdminStore();
  const donuts = Array.from(document.querySelectorAll("[data-sa-donut]"));
  if (!donuts.length) return;

  donuts.forEach((el) => {
    const kind = el.getAttribute("data-sa-donut");
    if (kind !== "license") return;

    const source = Array.isArray(store.licenseSegments) ? store.licenseSegments : [];
    const palette = ["#16a34a", "#f59e0b", "#3b82f6", "#8b5cf6", "#94a3b8"];
    const segments = source.map((s, idx) => ({
      label: s.label || s.plan || `Plan ${idx + 1}`,
      value: toNumber(s.value ?? s.count),
      color: s.color || palette[idx % palette.length],
    }));
    renderDonutSvg(el, segments);
  });
}

function initSuperAdminSettingsTabs() {
  const root = document.querySelector("[data-sa-settings]");
  if (!root) return;

  const tabButtons = Array.from(root.querySelectorAll("[data-sa-settings-tab]"));
  const panels = Array.from(root.querySelectorAll("[data-sa-settings-panel]"));
  if (!tabButtons.length || !panels.length) return;

  function setActive(tabName) {
    tabButtons.forEach((b) => b.classList.toggle("is-active", b.getAttribute("data-sa-settings-tab") === tabName));
    panels.forEach((p) => (p.style.display = p.getAttribute("data-sa-settings-panel") === tabName ? "block" : "none"));
  }

  tabButtons.forEach((b) => b.addEventListener("click", () => setActive(b.getAttribute("data-sa-settings-tab"))));
  setActive(tabButtons[0].getAttribute("data-sa-settings-tab"));
}

function downloadTextFile(text, filename, contentType) {
  const blob = new Blob([text], { type: contentType || "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderLineChartSvg(container, labels, values) {
  const width = container.clientWidth || 640;
  const height = container.clientHeight || 220;
  const padding = 26;
  const innerW = Math.max(10, width - padding * 2);
  const innerH = Math.max(10, height - padding * 2);

  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(1, max - min);

  const pts = values.map((v, i) => {
    const x = padding + (i / Math.max(1, values.length - 1)) * innerW;
    const y = padding + (1 - (v - min) / range) * innerH;
    return { x, y, v, label: labels[i] };
  });

  const pathD = pts
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(" ");

  const fillD = `${pathD} L${(padding + innerW).toFixed(1)},${(padding + innerH).toFixed(1)} L${padding.toFixed(1)},${(padding + innerH).toFixed(1)} Z`;

  const gridLines = 4;
  const grid = Array.from({ length: gridLines + 1 }).map((_, idx) => {
    const y = padding + (idx / gridLines) * innerH;
    return `<line x1="${padding}" y1="${y.toFixed(1)}" x2="${(padding + innerW).toFixed(1)}" y2="${y.toFixed(1)}" stroke="#e2e8f0" stroke-width="1" />`;
  });

  const dots = pts.map(
    (p) =>
      `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="#16a34a" stroke="#ffffff" stroke-width="2" />`
  );

  const xLabels = pts
    .map(
      (p) =>
        `<text x="${p.x.toFixed(1)}" y="${(padding + innerH + 18).toFixed(1)}" text-anchor="middle" font-size="11" fill="#64748b" font-weight="700">${escapeHtml(p.label)}</text>`
    )
    .join("");

  container.innerHTML = `
    <svg width="100%" height="100%" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="New zoo registrations (last 6 months)">
      <rect x="0" y="0" width="${width}" height="${height}" fill="#ffffff" />
      ${grid.join("")}
      <path d="${fillD}" fill="rgba(22, 163, 74, 0.10)" />
      <path d="${pathD}" fill="none" stroke="#16a34a" stroke-width="3" />
      ${dots.join("")}
      ${xLabels}
    </svg>
  `;
}

function renderDonutSvg(container, segments) {
  const size = Math.min(container.clientWidth || 180, container.clientHeight || 180);
  const stroke = 16;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const totalRaw = segments.reduce((acc, s) => acc + (s.value || 0), 0);
  const total = totalRaw > 0 ? totalRaw : 1;

  let offset = 0;
  const circles = segments
    .map((s) => {
      const pct = totalRaw > 0 ? (s.value || 0) / totalRaw : 0;
      const dash = pct * circumference;
      const gap = circumference - dash;
      const circle = `
        <circle
          r="${r.toFixed(2)}"
          cx="${cx.toFixed(2)}"
          cy="${cy.toFixed(2)}"
          fill="transparent"
          stroke="${s.color}"
          stroke-width="${stroke}"
          stroke-linecap="round"
          stroke-dasharray="${dash.toFixed(2)} ${gap.toFixed(2)}"
          stroke-dashoffset="${(-offset).toFixed(2)}"
        />`;
      offset += dash;
      return circle;
    })
    .join("\n");

  container.innerHTML = `
    <svg width="100%" height="100%" viewBox="0 0 ${size} ${size}" role="img" aria-label="License status distribution">
      <circle r="${r.toFixed(2)}" cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" fill="transparent" stroke="#e2e8f0" stroke-width="${stroke}" />
      <g transform="rotate(-90 ${cx} ${cy})">
        ${circles}
      </g>
      <text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="14" fill="#0f172a" font-weight="900">${totalRaw}</text>
      <text x="${cx}" y="${cy + 14}" text-anchor="middle" font-size="11" fill="#64748b" font-weight="800">Parks</text>
    </svg>
  `;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Compresses an image file client-side using canvas to keep payload well below Vercel's 4.5 MB limit.
 */
window.compressImageFile = function (file, maxWidth = 1920, maxHeight = 1080, quality = 0.82) {
  return new Promise((resolve) => {
    if (!file || !file.type || !file.type.startsWith("image/")) {
      return resolve(file);
    }
    if (file.type === "image/svg+xml" || file.type === "image/gif") {
      return resolve(file);
    }
    if (file.size < 400 * 1024) {
      return resolve(file);
    }

    const reader = new FileReader();
    reader.onload = function (e) {
      const img = new Image();
      img.onload = function () {
        let width = img.width;
        let height = img.height;
        if (width > maxWidth || height > maxHeight) {
          if (width / height > maxWidth / maxHeight) {
            height = Math.round((height * maxWidth) / width);
            width = maxWidth;
          } else {
            width = Math.round((width * maxHeight) / height);
            height = maxHeight;
          }
        }

        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        if (!ctx) return resolve(file);

        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);

        const outType = file.type === "image/webp" ? "image/webp" : "image/jpeg";
        const ext = file.type === "image/webp" ? ".webp" : ".jpg";

        canvas.toBlob(
          (blob) => {
            if (!blob || blob.size >= file.size) {
              return resolve(file);
            }
            const baseName = file.name.replace(/\.[^/.]+$/, "");
            const compressed = new File([blob], baseName + ext, {
              type: outType,
              lastModified: Date.now(),
            });
            resolve(compressed);
          },
          outType,
          quality
        );
      };
      img.onerror = function () {
        resolve(file);
      };
      img.src = e.target.result;
    };
    reader.onerror = function () {
      resolve(file);
    };
    reader.readAsDataURL(file);
  });
};

/**
 * Assigns a File object to an <input type="file"> via DataTransfer.
 */
window.setFileInputFile = function (input, file) {
  try {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    return true;
  } catch {
    return false;
  }
};


