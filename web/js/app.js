let currentConfig = {
  master_qq: "",
  bot_qq: "",
  api_provider: "baomiao",
  api_key: "",
  api_key_set: false,
  api_base: "https://api.baomiao.com/v1",
  model_name: "deepseek-chat"
};

let eventSource = null;
let currentStep = 1;

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  initEventStream();
  checkServiceStatus();
  setInterval(checkServiceStatus, 1000);
});

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const data = await res.json();
    currentConfig = { ...currentConfig, ...data };
    document.getElementById("master_qq").value = currentConfig.master_qq || "";
    document.getElementById("bot_qq").value = currentConfig.bot_qq || "";
    const baomiaoKeyEl = document.getElementById("baomiao_api_key");
    const deepseekKeyEl = document.getElementById("api_key");
    if (baomiaoKeyEl) baomiaoKeyEl.value = "";
    if (deepseekKeyEl) deepseekKeyEl.value = "";
    selectProvider(currentConfig.api_provider || "baomiao");
    if (currentConfig.install_dir) {
      document.getElementById("display-install-dir").textContent = currentConfig.install_dir;
    }
  } catch (err) {
    console.error("加载配置失败:", err);
  }
}

function selectProvider(provider) {
  currentConfig.api_provider = provider;
  document.querySelectorAll(".provider-card, .provider-choice, .provider-option, .deck-option, .provider-radio-card").forEach(el => {
    el.classList.toggle("active", el.dataset.provider === provider);
  });
  
  const baomiaoContainer = document.getElementById("baomiao-key-container");
  const deepseekContainer = document.getElementById("deepseek-key-container");
  
  if (provider === "baomiao") {
    currentConfig.api_base = "https://api.baomiao.com/v1";
    if (baomiaoContainer) baomiaoContainer.style.display = "block";
    if (deepseekContainer) deepseekContainer.style.display = "none";
  } else {
    currentConfig.api_base = "https://api.deepseek.com/v1";
    if (baomiaoContainer) baomiaoContainer.style.display = "none";
    if (deepseekContainer) deepseekContainer.style.display = "block";
  }
}

async function goToStep(step) {
  if (step === 2) {
    const master = document.getElementById("master_qq").value.trim();
    const bot = document.getElementById("bot_qq").value.trim();
    if (!/^\d{1,12}$/.test(master)) {
      alert("请填写正确的【主人大号 QQ】。");
      return;
    }
    if (!/^\d{1,12}$/.test(bot)) {
      alert("请填写正确的【机器人小号 QQ】。");
      return;
    }

    let inputKey = "";
    if (currentConfig.api_provider === "baomiao") {
      const el = document.getElementById("baomiao_api_key");
      inputKey = el ? el.value.trim() : "";
      if (!inputKey && !currentConfig.api_key_set) {
        inputKey = "bm-free-token";
      }
    } else {
      const el = document.getElementById("api_key");
      inputKey = el ? el.value.trim() : "";
      if (!inputKey && !currentConfig.api_key_set) {
        alert("请填写 DeepSeek 官方 API Key。");
        return;
      }
    }

    currentConfig.master_qq = master;
    currentConfig.bot_qq = bot;
    if (inputKey) {
      currentConfig.api_key = inputKey;
      currentConfig.api_key_set = true;
    }
    const saved = await saveConfig();
    if (!saved) return;
  }

  currentStep = step;
  document.querySelectorAll(".step-item").forEach((el, idx) => {
    el.classList.toggle("active", idx + 1 === step);
  });
  document.querySelectorAll(".card").forEach((el, idx) => {
    el.classList.toggle("active", idx + 1 === step);
  });
  if (step === 3) {
    checkServiceStatus();
  }
}

function openHelpModal() {
  const el = document.getElementById("help-modal");
  if (el) el.style.display = "flex";
}

function closeHelpModal(event) {
  if (event && event.target && event.target.id !== "help-modal" && !event.target.classList.contains("btn-modal-close")) {
    return;
  }
  const el = document.getElementById("help-modal");
  if (el) el.style.display = "none";
}

async function saveConfig() {
  const payload = { ...currentConfig };
  if (currentConfig.api_key_set && !payload.api_key) {
    delete payload.api_key;
  }
  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      alert("保存配置失败: " + (data.message || "参数错误"));
      return false;
    }
    currentConfig = { ...currentConfig, ...data.config, api_key: "" };
    return true;
  } catch (err) {
    console.error("保存配置失败:", err);
    alert("保存配置失败，请确认管家服务仍在运行。");
    return false;
  }
}

function setInstallButton(enabled, text) {
  const btn = document.getElementById("btn-start-install");
  btn.disabled = !enabled;
  btn.textContent = text;
}

function updateInstallStatus(state) {
  if (state.message) {
    const textEl = document.getElementById("status-text");
    if (textEl) textEl.textContent = state.message;
  }
  if (state.progress !== null && state.progress !== undefined) {
    const barEl = document.getElementById("progress-bar");
    if (barEl) barEl.style.width = state.progress + "%";
    const percentEl = document.getElementById("progress-percent");
    if (percentEl) percentEl.textContent = state.progress + "%";
  }
}

function toggleKeyVisibility() {
  const input = document.getElementById("api_key");
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
}

function toggleBaomiaoKeyVisibility() {
  const input = document.getElementById("baomiao_api_key");
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
}

function clearTerminal() {
  const terminal = document.getElementById("log-terminal");
  if (terminal) {
    terminal.innerHTML = '<div class="terminal-line">[系统] 控制台已清空。</div>';
  }
}

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    alert("已复制口令: " + text + "\n可以直接发送给 QQ 大肥鱼体验！");
  }).catch(() => {
    prompt("请手动复制口令:", text);
  });
}

async function waitForInstallation() {
  while (true) {
    const res = await fetch("/api/install/status");
    const state = await res.json();
    updateInstallStatus(state);
    if (state.state === "completed") return;
    if (state.state === "failed") {
      throw new Error(state.error || state.message || "部署失败");
    }
    await delay(500);
  }
}

async function startInstallation() {
  setInstallButton(false, "⏳ 正在部署组件，请稍候...");
  document.getElementById("status-text").textContent = "正在下载并校验 NapCat，准备 AstrBot 运行环境...";
  document.getElementById("progress-bar").style.width = "5%";

  try {
    const res = await fetch("/api/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.message || "无法启动部署任务");
    }
    await waitForInstallation();
    document.getElementById("progress-bar").style.width = "100%";
    appendLog("[系统] 全部组件与大肥鱼人设注入完毕，正在启动扫码。");
    await goToStep(3);
    await startServices();
    setInstallButton(false, "✅ 部署完成");
  } catch (err) {
    setInstallButton(true, "❌ 部署失败，点击重试");
    document.getElementById("status-text").textContent = "部署失败: " + err.message;
    appendLog("[系统] 部署失败: " + err.message);
  }
}

let qrPollingTimer = null;

function setLoginSuccessUI() {
  stopQrPolling();
  const placeholder = document.getElementById("qr-placeholder");
  const qrImg = document.getElementById("qr-image");
  const banner = document.getElementById("success-banner");
  const status = document.getElementById("service-status");
  const radarTag = document.querySelector(".qr-radar-tag");

  if (placeholder) {
    placeholder.style.display = "flex";
    placeholder.innerHTML = `
      <div class="active-mascot-wrapper" style="position: relative; width: 84px; height: 84px; margin: 0 auto 10px auto; animation: bounceIn 0.5s ease;">
        <img src="img/dafeiyu_logo.png" alt="大肥鱼" style="width: 84px; height: 84px; border-radius: 50%; border: 3px solid #38bdf8; box-shadow: 0 0 20px rgba(56, 189, 248, 0.45); object-fit: cover;">
        <span style="position: absolute; bottom: 2px; right: 2px; width: 16px; height: 16px; background: #10b981; border: 2.5px solid #0f172a; border-radius: 50%; box-shadow: 0 0 8px #10b981;"></span>
      </div>
      <p style="color: #10b981; font-weight: bold; font-size: 16px; margin: 0 0 4px 0;">大肥鱼已激活 · 在线中</p>
      <p style="color: #94a3b8; font-size: 12.5px; margin: 0; line-height: 1.4;">免扫码自动上线<br>随时给小号发消息对话</p>
    `;
  }
  if (qrImg) qrImg.style.display = "none";
  if (banner) banner.style.display = "flex";
  if (status) status.textContent = "大肥鱼已激活·在线中";
  if (radarTag) {
    radarTag.innerHTML = '<span class="radar-ping" style="background: #10b981;"></span><span style="color: #10b981; font-weight: 600;">大肥鱼状态：在线服务中</span>';
  }
}

function renderQrCode(qrData) {
  const qrImg = document.getElementById("qr-image");
  const placeholder = document.getElementById("qr-placeholder");
  if (!qrImg || !placeholder) return;
  if (qrData.startsWith("http")) {
    qrImg.src = "https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=" + encodeURIComponent(qrData);
  } else {
    qrImg.src = qrData;
  }
  qrImg.style.display = "block";
  placeholder.style.display = "none";
}

let isStartingServices = false;

async function checkServiceStatus() {
  try {
    const res = await fetch("/api/service/status");
    if (!res.ok) return;
    const data = await res.json();
    if (!data.success) return;

    if (data.is_logged_in) {
      setLoginSuccessUI();
      return;
    }

    if (data.has_qr && data.qr_data) {
      renderQrCode(data.qr_data);
      stopQrPolling();
      return;
    }

    if (currentStep === 3 && !data.running && !isStartingServices) {
      startServices();
    }
  } catch (_) {}
}

function startQrPolling() {
  stopQrPolling();
  qrPollingTimer = setInterval(checkServiceStatus, 1200);
}

function stopQrPolling() {
  if (qrPollingTimer) {
    clearInterval(qrPollingTimer);
    qrPollingTimer = null;
  }
}

async function relogin() {
  if (!confirm("确定要退出当前 QQ 账号并重新扫码吗？")) return;
  document.getElementById("service-status").textContent = "正在清理凭证…";
  document.getElementById("success-banner").style.display = "none";
  document.getElementById("qr-image").style.display = "none";
  const placeholder = document.getElementById("qr-placeholder");
  if (placeholder) {
    placeholder.style.display = "flex";
    placeholder.innerHTML = '<div class="scan-spinner"></div><p>正在生成全新登录二维码...</p>';
  }
  startQrPolling();
  try {
    const res = await fetch("/api/relogin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.message || "重新启动失败");
    }
  } catch (err) {
    alert("重新登录失败: " + err.message);
  }
}

async function startServices() {
  if (isStartingServices) return;
  isStartingServices = true;
  document.getElementById("service-status").textContent = "正在启动服务…";
  const placeholder = document.getElementById("qr-placeholder");
  if (placeholder) {
    placeholder.style.display = "flex";
    placeholder.innerHTML = '<div class="scan-spinner"></div><p>正在连接大肥鱼服务...</p>';
  }
  document.getElementById("qr-image").style.display = "none";
  document.getElementById("success-banner").style.display = "none";
  startQrPolling();

  try {
    const res = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.message || "服务启动失败");
    }
    document.getElementById("service-status").textContent = "服务运行中";
    checkServiceStatus();
  } catch (err) {
    document.getElementById("service-status").textContent = "启动失败";
    appendLog("[系统] 启动失败: " + err.message);
  } finally {
    isStartingServices = false;
  }
}

async function restartServices() {
  await stopServices();
  await delay(500);
  await startServices();
}

async function stopServices() {
  stopQrPolling();
  try {
    await fetch("/api/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    });
    document.getElementById("service-status").textContent = "已停止";
    document.getElementById("qr-image").style.display = "none";
    const placeholder = document.getElementById("qr-placeholder");
    if (placeholder) {
      placeholder.style.display = "flex";
      placeholder.innerHTML = "<p>服务已停止，点击上方按钮可重新启动</p>";
    }
  } catch (err) {
    console.error(err);
  }
}

function initEventStream() {
  eventSource = new EventSource("/api/events");
  eventSource.onmessage = event => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "log") {
        appendLog(`[${payload.tag}] ${payload.text}`);
      } else if (payload.type === "progress") {
        updateInstallStatus(payload);
      } else if (payload.type === "qr") {
        renderQrCode(payload.data);
        stopQrPolling();
        appendLog("[NapCat] 已捕获登录二维码，请使用手机 QQ 扫码。");
      } else if (payload.type === "login_success") {
        setLoginSuccessUI();
        appendLog("🎉 [系统] 登录成功！大肥鱼已正式就绪！");
      }
    } catch (err) {
      console.error(err);
    }
  };
}

function appendLog(line) {
  const terminal = document.getElementById("log-terminal");
  if (!terminal) return;
  const div = document.createElement("div");
  div.className = "terminal-line";
  div.textContent = line;
  terminal.appendChild(div);
  while (terminal.childElementCount > 200) {
    terminal.removeChild(terminal.firstElementChild);
  }
  terminal.scrollTop = terminal.scrollHeight;
}

async function unbindMaster() {
  if (!confirm("确定要解除当前主人绑定吗？\n\n解除后：\n1. 大肥鱼将清除主人专属绑定，恢复自由无主状态；\n2. 任何人都可以随时重新认领大肥鱼；\n3. 你也可以稍后随时在第1步重新认领。")) {
    return;
  }
  try {
    const res = await fetch("/api/unbind_master", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    });
    const data = await res.json();
    alert(data.message || "已成功解除主人绑定！");
    currentConfig.master_qq = "";
    const masterInput = document.getElementById("master-qq");
    if (masterInput) masterInput.value = "";
    const dispMaster = document.getElementById("display-master-qq");
    if (dispMaster) dispMaster.textContent = "无（自由模式）";
    appendLog("👑 [契约] 已成功解除主人绑定，大肥鱼恢复自由无主身。");
  } catch (err) {
    alert("解除绑定失败: " + err.message);
  }
}
