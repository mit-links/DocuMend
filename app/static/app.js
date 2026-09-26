// DocuMend Frontend Controller

let selectedFile = null;
let activeEventSource = null;
let currentJobId = null;

// Contextual help information for each input field
const INFO_DATA = {
  baseUrl: {
    title: "Server Base URL",
    icon: "fa-solid fa-server",
    content: `
      <p>The HTTP address of your local or network OpenAI-compatible LLM server.</p>
      <p class="font-semibold text-slate-700 mt-2">Supported Presets & Defaults:</p>
      <ul class="list-disc pl-4 space-y-1">
        <li><code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">http://localhost:1234/v1</code> &mdash; LM Studio default</li>
        <li><code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">http://localhost:11434/v1</code> &mdash; Ollama default</li>
        <li><code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">https://generativelanguage.googleapis.com/v1beta/openai/</code> &mdash; Google Gemini</li>
        <li><code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">https://api.openai.com/v1</code> &mdash; ChatGPT (OpenAI)</li>
        <li><code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">https://api.anthropic.com/v1</code> &mdash; Claude (Anthropic)</li>
      </ul>
      <p class="mt-2 text-slate-500">You can also specify remote LAN IP addresses (e.g., <code class="bg-slate-100 px-1 py-0.5 rounded">http://192.168.1.50:1234/v1</code>) if your model runs on another machine.</p>
    `
  },
  apiKey: {
    title: "API Key",
    icon: "fa-solid fa-key",
    content: `
      <p>Authentication token for your LLM server.</p>
      <p class="mt-1">Most local servers (like LM Studio and Ollama) do not require authentication. The placeholder <code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">not-needed</code> is passed by default to satisfy the OpenAI client specification.</p>
      <p class="mt-3 text-slate-800 font-semibold text-xs uppercase tracking-wider">How to get an API key:</p>
      <ul class="space-y-2 mt-2 text-xs">
        <li class="p-2 rounded-lg bg-slate-50 border border-slate-100">
          <div class="font-semibold text-slate-800">Google Gemini</div>
          <div class="text-slate-600 mt-0.5">Generate a key in <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener noreferrer" class="text-indigo-600 font-medium hover:underline inline-flex items-center space-x-1"><span>Google AI Studio</span> <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i></a>. Read the <a href="https://ai.google.dev/gemini-api/docs/api-key" target="_blank" rel="noopener noreferrer" class="text-indigo-600 hover:underline">Gemini API Key Documentation</a>.</div>
        </li>
        <li class="p-2 rounded-lg bg-slate-50 border border-slate-100">
          <div class="font-semibold text-slate-800">Anthropic Claude</div>
          <div class="text-slate-600 mt-0.5">Generate a key in the <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer" class="text-indigo-600 font-medium hover:underline inline-flex items-center space-x-1"><span>Anthropic Console</span> <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i></a>. Read the <a href="https://docs.anthropic.com/en/docs/initial-setup" target="_blank" rel="noopener noreferrer" class="text-indigo-600 hover:underline">Claude Setup Documentation</a>.</div>
        </li>
        <li class="p-2 rounded-lg bg-slate-50 border border-slate-100">
          <div class="font-semibold text-slate-800">ChatGPT (OpenAI)</div>
          <div class="text-slate-600 mt-0.5">Generate a secret key in the <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer" class="text-indigo-600 font-medium hover:underline inline-flex items-center space-x-1"><span>OpenAI Platform</span> <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i></a>. Read the <a href="https://platform.openai.com/docs/quickstart" target="_blank" rel="noopener noreferrer" class="text-indigo-600 hover:underline">OpenAI Quickstart Guide</a>.</div>
        </li>
      </ul>
      <p class="mt-2 text-slate-400 text-[11px]">API keys are stored strictly in memory for the duration of the request and are never written to disk.</p>
    `
  },
  modelSelect: {
    title: "Model Selection",
    icon: "fa-solid fa-microchip",
    content: `
      <p>The specific Large Language Model used to correct spelling and grammar in your document.</p>
      <p class="mt-1">Click the <strong class="text-indigo-600">Connect & Fetch</strong> button to automatically discover all models currently loaded or available on your server.</p>
      <p class="mt-2 text-slate-500">Recommended local models include: Gemma 4, Qwen 2.5 / 3, Llama 3.1, or Mistral.</p>
    `
  },
  fileUpload: {
    title: "Document Upload (.docx)",
    icon: "fa-solid fa-file-word",
    content: `
      <p>Upload a standard Microsoft Word document (<code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">.docx</code>).</p>
      <p class="font-semibold text-slate-700 mt-2">What DocuMend processes:</p>
      <ul class="list-disc pl-4 space-y-1">
        <li><strong>Body Paragraphs:</strong> Headings, text blocks, and bullet items.</li>
        <li><strong>Table Cells:</strong> Tables, headers, and grid cells.</li>
        <li><strong>Inline Formatting:</strong> Bold, italic, underline, fonts, and colors are preserved via sequence-matching diffs.</li>
      </ul>
      <p class="mt-2 text-slate-500">Headers and footers are preserved untouched to protect dynamic page numbers and document metadata.</p>
    `
  },
  concurrency: {
    title: "Parallel Requests (Concurrency)",
    icon: "fa-solid fa-sliders",
    content: `
      <p>Controls how many paragraphs are processed simultaneously by your LLM server.</p>
      <p class="mt-1">Enter any <strong>positive integer</strong> &ge; 1 (pre-filled with <strong>2</strong>).</p>
      <ul class="list-disc pl-4 space-y-1 mt-2">
        <li><strong>1:</strong> Conservative & lowest VRAM usage. Ideal for CPU-only inference or smaller GPUs.</li>
        <li><strong>2 (Recommended):</strong> Default balance between throughput and smooth local generation.</li>
        <li><strong>3&ndash;8+:</strong> Faster throughput if your hardware (VRAM/Compute) can handle concurrent requests.</li>
      </ul>
      <p class="mt-2 text-slate-500">Values less than 1 or non-integers will be rejected.</p>
    `
  },
  correctionMode: {
    title: "Output Mode",
    icon: "fa-solid fa-code-compare",
    content: `
      <p>Choose how DocuMend outputs corrections to your document:</p>
      <ul class="list-disc pl-4 space-y-2 mt-2">
        <li><strong>Direct Edit (Default):</strong> Directly applies corrections into the document text, preserving all original formatting (bold, italic, font, color, tables). The output document is clean and immediately ready to use.</li>
        <li><strong>Suggestions (Track Changes):</strong> Marks all modifications as standard Word Track Changes (<code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">&lt;w:ins&gt;</code> and <code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">&lt;w:del&gt;</code>). When opened in <strong>Microsoft Word</strong>, <strong>LibreOffice Writer</strong>, or <strong>Google Docs</strong>, you can review, accept, or reject each correction individually or all at once.</li>
      </ul>
    `
  }
};

// Modal functions
function showInfo(key) {
  const data = INFO_DATA[key];
  if (!data) return;

  document.getElementById("modalTitle").textContent = data.title;
  document.getElementById("modalIcon").className = data.icon + " text-lg";
  document.getElementById("modalBody").innerHTML = data.content;
  document.getElementById("infoModal").classList.remove("hidden");
}

function closeInfo() {
  document.getElementById("infoModal").classList.add("hidden");
}

let lastConnectionError = null;

function showErrorModal(title, summary, details) {
  const modal = document.getElementById("errorModal");
  if (!modal) return;
  document.getElementById("errorModalTitle").textContent = title || "Connection Failed";
  document.getElementById("errorModalSummary").textContent = summary || "An error occurred while connecting to the server.";
  document.getElementById("errorModalDetails").textContent = details || summary || "No details available.";
  const copyBtn = document.getElementById("copyBtnText");
  if (copyBtn) copyBtn.textContent = "Copy Details";
  modal.classList.remove("hidden");
}

function closeErrorModal() {
  const modal = document.getElementById("errorModal");
  if (modal) modal.classList.add("hidden");
}

function showLastErrorModal() {
  if (lastConnectionError) {
    showErrorModal("Connection Error", lastConnectionError.main, lastConnectionError.details);
  }
}

function copyErrorDetails() {
  const detailsEl = document.getElementById("errorModalDetails");
  if (!detailsEl || !detailsEl.textContent) return;
  navigator.clipboard.writeText(detailsEl.textContent).then(() => {
    const copyBtn = document.getElementById("copyBtnText");
    if (copyBtn) {
      copyBtn.textContent = "Copied!";
      setTimeout(() => { copyBtn.textContent = "Copy Details"; }, 2000);
    }
  });
}

// Close modals on escape key or backdrop click
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeInfo();
    closeErrorModal();
  }
});

document.getElementById("infoModal").addEventListener("click", (e) => {
  if (e.target.id === "infoModal") closeInfo();
});

const errorModalElem = document.getElementById("errorModal");
if (errorModalElem) {
  errorModalElem.addEventListener("click", (e) => {
    if (e.target.id === "errorModal") closeErrorModal();
  });
}

function setPreset(url) {
  document.getElementById("serverUrl").value = url;
  const keyField = document.getElementById("apiKey");
  const isCloud = url.startsWith("https://");

  if (isCloud) {
    if (!keyField.value || keyField.value === "not-needed") {
      keyField.value = "";
      keyField.placeholder = "Enter your API key";
      keyField.focus();
    }
  } else {
    if (!keyField.value) {
      keyField.value = "not-needed";
    }
  }

  // Do not attempt connection automatically; prompt user to press "Connect & Fetch"
  updateConnectionBadge("checking", "Click Connect & Fetch");
  const modelSelect = document.getElementById("modelSelect");
  if (modelSelect) {
    modelSelect.innerHTML = '<option value="">Click "Connect & Fetch" to discover models</option>';
  }
  checkCanStart();
}

// Update connection status badge (top right header)
function updateConnectionBadge(status, text = null) {
  const badge = document.getElementById("connectionBadge");
  const badgeText = document.getElementById("badgeText");

  if (status === "connected") {
    const label = text || "Connected";
    badgeText.textContent = label;
    badge.className = "flex items-center space-x-2 text-xs font-medium px-3 py-1.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 transition-colors";
    badge.title = "Connected to LLM server";
    badge.onclick = null;
    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-500"></span><span id="badgeText">${label}</span>`;
  } else if (status === "checking") {
    const label = text || "Connecting...";
    badgeText.textContent = label;
    badge.className = "flex items-center space-x-2 text-xs font-medium px-3 py-1.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 transition-colors";
    badge.title = "Checking server connection...";
    badge.onclick = null;
    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span><span id="badgeText">${label}</span>`;
  } else {
    // Generic error message so the top-right status pill remains clean, compact, and never overflows
    const label = "Connection Failed";
    badgeText.textContent = label;
    badge.className = "flex items-center space-x-2 text-xs font-medium px-3 py-1.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 transition-colors cursor-pointer hover:bg-rose-100 hover:border-rose-300 shadow-sm";
    badge.title = "Connection failed — click to view full error details";
    badge.onclick = () => showLastErrorModal();
    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-rose-500"></span><span id="badgeText">${label}</span><i class="fa-solid fa-circle-info text-[11px] text-rose-500 ml-0.5"></i>`;
  }
}

// Fetch models from LLM server via backend proxy
async function fetchModels(isUserClick = false) {
  const baseUrl = document.getElementById("serverUrl").value.trim();
  const apiKey = document.getElementById("apiKey").value.trim();
  const modelSelect = document.getElementById("modelSelect");
  const refreshIcon = document.getElementById("refreshIcon");

  refreshIcon.classList.add("fa-spin");
  updateConnectionBadge("checking", "Connecting...");

  try {
    const params = new URLSearchParams({ base_url: baseUrl });
    if (apiKey) params.append("api_key", apiKey);

    const response = await fetch(`/api/models?${params.toString()}`);
    const data = await response.json();

    if (data.status === "connected" && data.models && data.models.length > 0) {
      lastConnectionError = null;
      modelSelect.innerHTML = "";
      data.models.forEach((m, idx) => {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        if (idx === 0) opt.selected = true;
        modelSelect.appendChild(opt);
      });
      updateConnectionBadge("connected", `Connected (${data.models.length} model${data.models.length > 1 ? "s" : ""})`);
      checkCanStart();
    } else {
      modelSelect.innerHTML = '<option value="">No models found on server</option>';
      const mainMsg = data.error || "No models found on server";
      const fullDetails = data.raw_error || data.error || `Could not find any models on server at ${baseUrl}`;
      lastConnectionError = { main: mainMsg, details: fullDetails };

      updateConnectionBadge("error");
      checkCanStart();

      if (isUserClick) {
        showErrorModal("Connection Failed", mainMsg, fullDetails);
      }
    }
  } catch (err) {
    modelSelect.innerHTML = '<option value="">Error connecting to server</option>';
    const mainMsg = "Connection error";
    const fullDetails = err.message || String(err);
    lastConnectionError = { main: mainMsg, details: fullDetails };

    updateConnectionBadge("error");
    checkCanStart();

    if (isUserClick) {
      showErrorModal("Connection Failed", mainMsg, fullDetails);
    }
  } finally {
    refreshIcon.classList.remove("fa-spin");
  }
}

// File dropzone management
const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");

dropZone.addEventListener("click", () => fileInput.click());

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("border-indigo-500", "bg-indigo-50/50");
});

dropZone.addEventListener("dragleave", (e) => {
  e.preventDefault();
  dropZone.classList.remove("border-indigo-500", "bg-indigo-50/50");
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("border-indigo-500", "bg-indigo-50/50");
  if (e.dataTransfer.files.length > 0) {
    handleFile(e.dataTransfer.files[0]);
  }
});

fileInput.addEventListener("change", (e) => {
  if (e.target.files.length > 0) {
    handleFile(e.target.files[0]);
  }
  e.target.value = "";
});

function handleFile(file) {
  if (!file.name.toLowerCase().endsWith(".docx")) {
    alert("Please select a Microsoft Word (.docx) file.");
    return;
  }
  selectedFile = file;

  const fileInfo = document.getElementById("selectedFileInfo");
  const fileName = document.getElementById("selectedFileName");
  const fileSize = document.getElementById("selectedFileSize");

  fileName.textContent = file.name;
  fileSize.textContent = `(${(file.size / 1024).toFixed(1)} KB)`;
  fileInfo.classList.remove("hidden");

  checkCanStart();
}

function getValidConcurrency() {
  const input = document.getElementById("concurrencyInput");
  if (!input) return 2;
  const raw = input.value.trim();
  const val = Number(raw);
  if (!raw || isNaN(val) || !Number.isInteger(val) || val < 1) {
    return null;
  }
  return val;
}

function validateConcurrencyUI() {
  const input = document.getElementById("concurrencyInput");
  const errorEl = document.getElementById("concurrencyError");
  const valid = getValidConcurrency() !== null;

  if (!valid) {
    if (errorEl) errorEl.classList.remove("hidden");
    if (input) input.classList.add("border-rose-500", "ring-1", "ring-rose-500");
  } else {
    if (errorEl) errorEl.classList.add("hidden");
    if (input) input.classList.remove("border-rose-500", "ring-1", "ring-rose-500");
  }
  checkCanStart();
  return valid;
}

function checkCanStart() {
  const modelSelect = document.getElementById("modelSelect");
  const startBtn = document.getElementById("startProcessBtn");

  const hasFile = selectedFile !== null;
  const hasModel = modelSelect.value && modelSelect.value.trim() !== "";
  const hasValidConcurrency = getValidConcurrency() !== null;

  startBtn.disabled = !(hasFile && hasModel && hasValidConcurrency);
}

document.getElementById("modelSelect").addEventListener("change", async () => {
  checkCanStart();
  const selectedModel = document.getElementById("modelSelect").value;
  if (selectedModel) {
    try {
      const formData = new FormData();
      formData.append("base_url", document.getElementById("serverUrl").value.trim());
      formData.append("api_key", document.getElementById("apiKey").value.trim());
      formData.append("active_model", selectedModel);
      const res = await fetch("/api/models/eject", { method: "POST", body: formData });
      const data = await res.json();
      if (data.ejected && data.ejected.length > 0) {
        console.info("Ejected inactive models to free VRAM:", data.ejected);
      }
    } catch (err) {
      // Best-effort operation, ignore failures
    }
  }
});
document.getElementById("concurrencyInput").addEventListener("input", validateConcurrencyUI);
document.getElementById("concurrencyInput").addEventListener("change", validateConcurrencyUI);

// Start document processing
async function startProcessing() {
  if (!selectedFile) return;

  const concurrency = getValidConcurrency();
  if (concurrency === null) {
    validateConcurrencyUI();
    document.getElementById("concurrencyInput").focus();
    return;
  }

  const startBtn = document.getElementById("startProcessBtn");
  const stopBtn = document.getElementById("stopProcessBtn");
  const progressCard = document.getElementById("progressCard");
  const progressBar = document.getElementById("progressBar");
  const progressPercent = document.getElementById("progressPercent");
  const progressCounter = document.getElementById("progressCounter");
  const progressStatus = document.getElementById("progressStatus");
  const currentSnippetText = document.getElementById("currentSnippetText");
  const downloadSection = document.getElementById("downloadSection");
  const progressSpinner = document.getElementById("progressSpinner");
  const progressTitle = document.getElementById("progressTitle");

  startBtn.disabled = true;
  if (stopBtn) {
    stopBtn.classList.remove("hidden");
    stopBtn.disabled = false;
    stopBtn.innerHTML = '<i class="fa-solid fa-stop text-xs"></i><span>Stop</span>';
  }
  downloadSection.classList.add("hidden");
  const statsSection = document.getElementById("statsSection");
  if (statsSection) statsSection.classList.add("hidden");
  const errorBanner = document.getElementById("errorBanner");
  if (errorBanner) errorBanner.classList.add("hidden");
  progressCard.classList.remove("hidden");
  progressBar.style.width = "0%";
  progressBar.className = "bg-gradient-to-r from-indigo-500 to-violet-600 h-3 rounded-full transition-all duration-300";
  progressPercent.textContent = "0%";
  progressCounter.textContent = "Uploading document...";
  progressStatus.textContent = "Uploading...";
  currentSnippetText.textContent = "Preparing document pipeline...";
  progressSpinner.className = "fa-solid fa-spinner fa-spin text-indigo-600";
  progressTitle.textContent = "Processing Document...";

  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("base_url", document.getElementById("serverUrl").value.trim());
  formData.append("api_key", document.getElementById("apiKey").value.trim());
  formData.append("model", document.getElementById("modelSelect").value.trim());
  formData.append("concurrency", concurrency.toString());

  const modeRadio = document.querySelector('input[name="correctionMode"]:checked');
  const mode = modeRadio ? modeRadio.value : "edit";
  formData.append("mode", mode);

  try {
    const res = await fetch("/api/process", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Upload failed");
    }

    const job = await res.json();
    currentJobId = job.job_id;
    connectSSE(job.stream_url);

  } catch (err) {
    progressStatus.textContent = "Error";
    currentSnippetText.textContent = "Upload failed.";
    progressSpinner.className = "fa-solid fa-triangle-exclamation text-rose-600";
    progressTitle.textContent = "Processing Failed";
    progressBar.className = "bg-rose-500 h-3 rounded-full transition-all duration-300";
    const errorBanner = document.getElementById("errorBanner");
    const errorBannerText = document.getElementById("errorBannerText");
    if (errorBanner && errorBannerText) {
      errorBannerText.textContent = err.message;
      errorBanner.classList.remove("hidden");
    }
    if (stopBtn) stopBtn.classList.add("hidden");
    startBtn.disabled = false;
  }
}

// Connect to Server-Sent Events stream for live progress
function connectSSE(streamUrl) {
  if (activeEventSource) {
    activeEventSource.close();
  }

  const progressBar = document.getElementById("progressBar");
  const progressPercent = document.getElementById("progressPercent");
  const progressCounter = document.getElementById("progressCounter");
  const progressStatus = document.getElementById("progressStatus");
  const currentSnippetText = document.getElementById("currentSnippetText");
  const downloadSection = document.getElementById("downloadSection");
  const manualDownloadBtn = document.getElementById("manualDownloadBtn");
  const progressSpinner = document.getElementById("progressSpinner");
  const progressTitle = document.getElementById("progressTitle");
  const startBtn = document.getElementById("startProcessBtn");
  const stopBtn = document.getElementById("stopProcessBtn");

  activeEventSource = new EventSource(streamUrl);

  activeEventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.status === "processing" || data.status === "pending") {
        const percent = data.percent || 0;
        progressBar.style.width = `${percent}%`;
        progressPercent.textContent = `${percent}%`;
        progressCounter.textContent = `Processing item ${data.processed} of ${data.total}`;
        progressStatus.textContent = "Correcting text...";
        if (data.snippet) {
          currentSnippetText.textContent = data.snippet;
        }
      } else if (data.status === "completed") {
        progressBar.style.width = "100%";
        progressPercent.textContent = "100%";
        progressCounter.textContent = `Completed ${data.total} items`;
        progressStatus.textContent = "Done!";
        const isSuggest = data.mode === "suggest" || (data.stats && data.stats.mode === "suggest");
        if (isSuggest) {
          currentSnippetText.textContent = "Revisions saved as Word Track Changes. Open in Word or LibreOffice to review, accept, or reject suggestions.";
          progressTitle.textContent = "Suggestions Completed!";
        } else {
          currentSnippetText.textContent = "Document formatting preserved and updated successfully.";
          progressTitle.textContent = "Correction Completed!";
        }
        if (stopBtn) stopBtn.classList.add("hidden");

        // Display performance stats
        const renderStats = (stats) => {
          if (!stats) return;
          const statsSection = document.getElementById("statsSection");
          const statElapsedTime = document.getElementById("statElapsedTime");
          const statWordsPerSec = document.getElementById("statWordsPerSec");
          const statTotalWords = document.getElementById("statTotalWords");
          const statTokCard = document.getElementById("statTokPerSecCard");
          const statTokensPerSec = document.getElementById("statTokensPerSec");

          if (statElapsedTime) statElapsedTime.textContent = `${stats.elapsed_seconds}s`;
          if (statWordsPerSec) statWordsPerSec.textContent = `${stats.words_per_second} w/s`;
          if (statTotalWords) {
            const extra = stats.revisions_count !== undefined ? ` (${stats.revisions_count} revisions)` : "";
            statTotalWords.textContent = `${stats.total_words} words checked${extra}`;
          }

          if (stats.tokens_per_second !== null && stats.tokens_per_second !== undefined) {
            if (statTokensPerSec) statTokensPerSec.textContent = `${stats.tokens_per_second} tok/s`;
            if (statTokCard) statTokCard.classList.remove("hidden");
          } else {
            if (statTokCard) statTokCard.classList.add("hidden");
          }

          if (statsSection) statsSection.classList.remove("hidden");
        };

        if (data.stats) {
          renderStats(data.stats);
        } else if (data.job_id) {
          fetch(`/api/jobs/${data.job_id}`)
            .then(res => res.json())
            .then(jobData => {
              if (jobData.stats) renderStats(jobData.stats);
            })
            .catch(err => console.warn("Failed to fetch fallback job stats:", err));
        }

        downloadSection.classList.remove("hidden");
        const downloadUrl = data.download_url || `/api/jobs/${data.job_id}/download`;
        manualDownloadBtn.href = downloadUrl;
        const downloadLabel = downloadSection.querySelector("div span");
        if (downloadLabel) {
          downloadLabel.textContent = isSuggest
            ? "Suggestions ready! Open in Word or LibreOffice to accept/reject changes."
            : "Document successfully corrected and downloaded!";
        }

        // Trigger automatic browser download
        const hiddenLink = document.createElement("a");
        hiddenLink.href = downloadUrl;
        hiddenLink.download = "";
        document.body.appendChild(hiddenLink);
        hiddenLink.click();
        document.body.removeChild(hiddenLink);

        activeEventSource.close();
        startBtn.disabled = false;

      } else if (data.status === "cancelled") {
        progressStatus.textContent = "Cancelled";
        currentSnippetText.textContent = data.message || "Processing was stopped by user.";
        progressSpinner.className = "fa-solid fa-ban text-amber-600";
        progressTitle.textContent = "Processing Stopped";
        progressBar.className = "bg-amber-500 h-3 rounded-full transition-all duration-300";
        if (stopBtn) stopBtn.classList.add("hidden");
        activeEventSource.close();
        startBtn.disabled = false;

      } else if (data.status === "failed") {
        progressStatus.textContent = "Failed";
        currentSnippetText.textContent = "Processing halted due to error.";
        progressSpinner.className = "fa-solid fa-circle-xmark text-rose-600";
        progressTitle.textContent = "Processing Stopped due to Error";
        progressBar.className = "bg-rose-500 h-3 rounded-full transition-all duration-300";
        const errorBanner = document.getElementById("errorBanner");
        const errorBannerText = document.getElementById("errorBannerText");
        if (errorBanner && errorBannerText) {
          errorBannerText.textContent = data.error || "An error occurred during processing.";
          errorBanner.classList.remove("hidden");
        }
        if (stopBtn) stopBtn.classList.add("hidden");
        activeEventSource.close();
        startBtn.disabled = false;
      }
    } catch (err) {
      console.error("Error parsing SSE data", err);
    }
  };

  activeEventSource.onerror = async (err) => {
    console.warn("SSE connection error or closed:", err);
    if (currentJobId && activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
      try {
        const res = await fetch(`/api/jobs/${currentJobId}`);
        if (res.ok) {
          const data = await res.json();
          if (data.status === "failed") {
            const errorBanner = document.getElementById("errorBanner");
            const errorBannerText = document.getElementById("errorBannerText");
            if (errorBanner && errorBannerText) {
              errorBannerText.textContent = data.error_message || "An error occurred during processing.";
              errorBanner.classList.remove("hidden");
            }
            progressStatus.textContent = "Failed";
            progressSpinner.className = "fa-solid fa-circle-xmark text-rose-600";
            progressTitle.textContent = "Processing Stopped due to Error";
            progressBar.className = "bg-rose-500 h-3 rounded-full transition-all duration-300";
            if (stopBtn) stopBtn.classList.add("hidden");
            startBtn.disabled = false;
          } else if (data.status === "completed" || data.status === "cancelled") {
            startBtn.disabled = false;
            if (stopBtn) stopBtn.classList.add("hidden");
          }
        }
      } catch (pollErr) {
        console.error("Failed to query fallback job status after SSE disconnect:", pollErr);
        startBtn.disabled = false;
      }
    }
  };
}

// Stop ongoing document processing
async function stopProcessing() {
  if (!currentJobId) return;

  const stopBtn = document.getElementById("stopProcessBtn");
  const startBtn = document.getElementById("startProcessBtn");
  const progressStatus = document.getElementById("progressStatus");
  const currentSnippetText = document.getElementById("currentSnippetText");

  if (stopBtn) {
    stopBtn.disabled = true;
    stopBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-xs"></i><span>Stopping...</span>';
  }
  if (progressStatus) {
    progressStatus.textContent = "Stopping...";
  }
  if (currentSnippetText) {
    currentSnippetText.textContent = "Stopping document pipeline and cancelling pending requests...";
  }

  try {
    const res = await fetch(`/api/jobs/${currentJobId}/cancel`, {
      method: "POST",
    });
    const data = await res.json();
    console.info("Job cancellation result:", data);
  } catch (err) {
    console.error("Failed to cancel job:", err);
    if (stopBtn) {
      stopBtn.disabled = false;
      stopBtn.innerHTML = '<i class="fa-solid fa-stop text-xs"></i><span>Stop Processing</span>';
    }
    if (startBtn) {
      startBtn.disabled = false;
    }
  }
}

// Initial connection check on page load
document.addEventListener("DOMContentLoaded", () => {
  fetchModels();
});
