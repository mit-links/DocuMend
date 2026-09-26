// DocuMend Frontend Controller

let selectedFile = null;
let activeEventSource = null;

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
      <ul class="list-disc pl-4 space-y-1 mt-1">
        <li><strong>1:</strong> Conservative & lowest VRAM usage. Best for small GPUs or CPU-only inference.</li>
        <li><strong>2 (Recommended):</strong> Balances fast throughput with smooth local inference.</li>
        <li><strong>3&ndash;4:</strong> Faster throughput if you have high-end GPU VRAM.</li>
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

// Close modal on escape key or backdrop click
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeInfo();
});

document.getElementById("infoModal").addEventListener("click", (e) => {
  if (e.target.id === "infoModal") closeInfo();
});

function setPreset(url) {
  document.getElementById("serverUrl").value = url;
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

function checkCanStart() {
  const modelSelect = document.getElementById("modelSelect");
  const startBtn = document.getElementById("startProcessBtn");

  const hasFile = selectedFile !== null;
  const hasModel = modelSelect.value && modelSelect.value.trim() !== "";

  startBtn.disabled = !(hasFile && hasModel);
}

document.getElementById("modelSelect").addEventListener("change", checkCanStart);

// Start document processing
async function startProcessing() {
  if (!selectedFile) return;

  const startBtn = document.getElementById("startProcessBtn");
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
  downloadSection.classList.add("hidden");
  progressCard.classList.remove("hidden");
  progressBar.style.width = "0%";
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
  formData.append("concurrency", document.getElementById("concurrencySelect").value);

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
    connectSSE(job.stream_url);

  } catch (err) {
    progressStatus.textContent = "Error";
    currentSnippetText.textContent = err.message;
    progressSpinner.className = "fa-solid fa-triangle-exclamation text-rose-600";
    progressTitle.textContent = "Processing Failed";
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

      } else if (data.status === "failed") {
        progressStatus.textContent = "Failed";
        currentSnippetText.textContent = data.error || "An error occurred during processing.";
        progressSpinner.className = "fa-solid fa-circle-xmark text-rose-600";
        progressTitle.textContent = "Processing Failed";
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

// Initial connection check on page load
document.addEventListener("DOMContentLoaded", () => {
  fetchModels();
});
