let currentConfig = {
  master_qq: "",
  bot_qq: "",
  api_provider: "baomiao",
  api_key: "",
  api_base: "https://api.deepseek.com/v1",
  model_name: "deepseek-chat"
};

let eventSource = null;

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  initEventStream();
});

// 从后端读取配置
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      const data = await res.json();
      currentConfig = { ...currentConfig, ...data };
      document.getElementById("master_qq").value = currentConfig.master_qq || "";
      document.getElementById("bot_qq").value = currentConfig.bot_qq || "";
      document.getElementById("api_key").value = currentConfig.api_key || "";
      selectProvider(currentConfig.api_provider || "baomiao");
      if (currentConfig.install_dir) {
        document.getElementById("display-install-dir").innerText = currentConfig.install_dir;
      }
    }
  } catch (err) {
    console.error("加载配置失败:", err);
  }
}

// 算力源选择切换
function selectProvider(provider) {
  currentConfig.api_provider = provider;
  document.querySelectorAll(".provider-card").forEach(el => {
    el.classList.toggle("active", el.dataset.provider === provider);
  });

  const keyContainer = document.getElementById("key-input-container");
  if (provider === "deepseek") {
    keyContainer.style.display = "block";
  } else {
    keyContainer.style.display = "none";
  }
}

// 步骤卡片切换
function goToStep(step) {
  if (step === 2) {
    // 校验第 1 步必填项
    const master = document.getElementById("master_qq").value.trim();
    const bot = document.getElementById("bot_qq").value.trim();
    if (!master) {
      alert("请填写【主人大号 QQ】！这是大肥鱼识别唯一主人并防止被盗刷的核心凭证。");
      return;
    }
    if (!bot) {
      alert("请填写【机器人小号 QQ】！");
      return;
    }

    currentConfig.master_qq = master;
    currentConfig.bot_qq = bot;
    currentConfig.api_key = document.getElementById("api_key").value.trim();

    // 保存到后端
    saveConfig();
  }

  document.querySelectorAll(".step-item").forEach((el, idx) => {
    el.classList.toggle("active", idx + 1 === step);
  });

  document.querySelectorAll(".card").forEach((el, idx) => {
    el.classList.toggle("active", idx + 1 === step);
  });
}

// 保存配置到后端
async function saveConfig() {
  try {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentConfig)
    });
  } catch (err) {
    console.error("保存配置失败:", err);
  }
}

// 开始全自动安装部署
async function startInstallation() {
  const btn = document.getElementById("btn-start-install");
  btn.disabled = true;
  btn.innerText = "⏳ 正在极速部署组件，请稍候...";

  document.getElementById("status-text").innerText = "正在通过暴喵专属专线下载 NapCat 与 AstrBot 核心组件...";
  document.getElementById("progress-bar").style.width = "10%";

  try {
    const res = await fetch("/api/install", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      document.getElementById("status-text").innerText = "✅ 组件校验与配置写入完成！正在准备启动扫码...";
      document.getElementById("progress-bar").style.width = "100%";
      appendLog("[系统] 全部组件与大肥鱼人设注入完毕，自动进入扫码激活阶段！");
      
      setTimeout(() => {
        goToStep(3);
        startServices();
      }, 1200);
    } else {
      btn.disabled = false;
      btn.innerText = "❌ 部署失败，点击重试";
      alert("部署失败: " + (data.message || "网络连接异常"));
    }
  } catch (err) {
    btn.disabled = false;
    btn.innerText = "❌ 部署失败，点击重试";
    console.error(err);
  }
}

// 启动服务并拉起二维码
async function startServices() {
  document.getElementById("service-status").innerText = "正在启动服务...";
  document.getElementById("qr-placeholder").style.display = "flex";
  document.getElementById("qr-image").style.display = "none";
  document.getElementById("success-banner").style.display = "none";

  try {
    const res = await fetch("/api/start", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      document.getElementById("service-status").innerText = "服务运行中";
    }
  } catch (err) {
    console.error("启动失败:", err);
  }
}

// 重启服务/刷新二维码
function restartServices() {
  stopServices().then(() => {
    setTimeout(startServices, 1000);
  });
}

// 停止服务
async function stopServices() {
  try {
    await fetch("/api/stop", { method: "POST" });
    document.getElementById("service-status").innerText = "已停止";
    document.getElementById("qr-image").style.display = "none";
    document.getElementById("qr-placeholder").style.display = "flex";
    document.getElementById("qr-placeholder").innerHTML = "<p>服务已停止，点击上方按钮可重新启动</p>";
  } catch (err) {
    console.error(err);
  }
}

// 建立 SSE 实时状态与日志流
function initEventStream() {
  eventSource = new EventSource("/api/events");

  eventSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "log") {
        appendLog(`[${payload.tag}] ${payload.text}`);
      } else if (payload.type === "progress") {
        if (payload.progress !== null) {
          document.getElementById("progress-bar").style.width = payload.progress + "%";
        }
        if (payload.message) {
          document.getElementById("status-text").innerText = payload.message;
        }
      } else if (payload.type === "qr") {
        // 显示二维码
        const qrImg = document.getElementById("qr-image");
        const placeholder = document.getElementById("qr-placeholder");
        qrImg.src = payload.data;
        qrImg.style.display = "block";
        placeholder.style.display = "none";
        appendLog("[NapCat] 已捕获登录二维码，请使用手机 QQ 扫码！");
      } else if (payload.type === "login_success") {
        document.getElementById("success-banner").style.display = "block";
        document.getElementById("service-status").innerText = "大肥鱼已激活·在线中";
        appendLog("🎉 [系统] 登录成功！大肥鱼已正式就绪！");
      }
    } catch (e) {
      console.error(e);
    }
  };
}

function appendLog(line) {
  const terminal = document.getElementById("log-terminal");
  if (!terminal) return;
  const div = document.createElement("div");
  div.className = "terminal-line";
  div.innerText = line;
  terminal.appendChild(div);
  terminal.scrollTop = terminal.scrollHeight;
}
