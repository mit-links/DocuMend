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
      <p class="font-semibold text-slate-700 mt-2">Common Defaults:</p>
      <ul class="list-disc pl-4 space-y-1">
        <li><code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">http://localhost:1234/v1</code> &mdash; LM Studio default</li>
        <li><code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">http://localhost:11434/v1</code> &mdash; Ollama default</li>
        <li><code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">http://localhost:8080/v1</code> &mdash; LocalAI / llama.cpp</li>
      </ul>
      <p class="mt-2 text-slate-500">You can also specify remote LAN IP addresses (e.g., <code class="bg-slate-100 px-1 py-0.5 rounded">http://192.168.1.50:1234/v1</code>) if your model runs on another machine.</p>
    `
  },
  apiKey: {
    title: "API Key (Optional)",
    icon: "fa-solid fa-key",
    content: `
      <p>Authentication token for your LLM server.</p>
      <p class="mt-1">Most local servers (like LM Studio and Ollama) do not require authentication. The placeholder <code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-600">not-needed</code> is passed by default to satisfy the OpenAI client specification.</p>
      <p class="mt-2 text-slate-500">If connecting to a secured local gateway, vLLM instance with API keys, or remote endpoint, enter your secret key here.</p>
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

// Close modal on escape key or backdrop click
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeInfo();
});

document.getElementById("infoModal").addEventListener("click", (e) => {
  if (e.target.id === "infoModal") closeInfo();
});

function setPreset(url) {
  document.getElementById("serverUrl").value = url;
  const keyField = document.getElementById("apiKey");
  if (url.includes("googleapis.com")) {
    if (!keyField.value || keyField.value === "not-needed") {
      keyField.value = "";
      keyField.placeholder = "Paste Gemini API key (AIzaSy...)";
      keyField.focus();
      updateConnectionBadge("checking", "Enter Gemini API Key");
      return;
    }
  } else {
    if (!keyField.value) {
      keyField.value = "not-needed";
    }
  }
  fetchModels();
}

// Update connection status badge
function updateConnectionBadge(status, text) {
  const badge = document.getElementById("connectionBadge");
  const badgeText = document.getElementById("badgeText");
  const statusDesc = document.getElementById("serverStatusDesc");

  badgeText.textContent = text;
  if (statusDesc) statusDesc.textContent = text;

  if (status === "connected") {
    badge.className = "flex items-center space-x-2 text-xs font-medium px-3 py-1.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 transition-colors";
    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-500"></span><span id="badgeText">${text}</span>`;
  } else if (status === "checking") {
    badge.className = "flex items-center space-x-2 text-xs font-medium px-3 py-1.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 transition-colors";
    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span><span id="badgeText">${text}</span>`;
  } else {
    badge.className = "flex items-center space-x-2 text-xs font-medium px-3 py-1.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 transition-colors";
    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-rose-500"></span><span id="badgeText">${text}</span>`;
  }
}

// Fetch models from LLM server via backend proxy
async function fetchModels() {
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
      const errMsg = data.error ? (data.error.length > 40 ? data.error.slice(0, 40) + "..." : data.error) : "No models found";
      updateConnectionBadge("error", `Server unreachable: ${errMsg}`);
      checkCanStart();
    }
  } catch (err) {
    modelSelect.innerHTML = '<option value="">Error connecting to server</option>';
    updateConnectionBadge("error", "Connection error");
    checkCanStart();
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
        currentSnippetText.textContent = "Document formatting preserved and updated successfully.";
        progressSpinner.className = "fa-solid fa-circle-check text-emerald-600";
        progressTitle.textContent = "Correction Completed!";
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
          if (statTotalWords) statTotalWords.textContent = `${stats.total_words} words checked`;

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

  activeEventSource.onerror = (err) => {
    console.warn("SSE connection error", err);
  };
}

// Stop ongoing document processing
async function stopProcessing() {
  if (!currentJobId) return;

  const stopBtn = document.getElementById("stopProcessBtn");
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
  }
}

// Initial connection check on page load
document.addEventListener("DOMContentLoaded", () => {
  fetchModels();
});
