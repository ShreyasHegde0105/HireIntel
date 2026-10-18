document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const matchForm = document.getElementById("match-form");
    const jobDescInput = document.getElementById("job-desc-input");
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const fileList = document.getElementById("file-list");
    const fileWarning = document.getElementById("file-warning");
    const uploadLimits = document.getElementById("upload-limits");
    const sampleBtn = document.getElementById("sample-btn");
    const accessCodeGroup = document.getElementById("access-code-group");
    const accessCodeInput = document.getElementById("access-code-input");
    const submitBtn = document.getElementById("submit-btn");
    const statusBadge = document.getElementById("status-badge");
    const statusText = document.getElementById("status-text");
    const extractReqBtn = document.getElementById("extract-req-btn");
    const reqEditor = document.getElementById("req-editor");
    const reqList = document.getElementById("req-list");
    const addReqBtn = document.getElementById("add-req-btn");
    const clearReqBtn = document.getElementById("clear-req-btn");
    const notAssessable = document.getElementById("not-assessable");
    const notAssessableList = document.getElementById("not-assessable-list");
    const notAssessableCount = document.getElementById("not-assessable-count");

    // State Containers
    const stateEmpty = document.getElementById("state-empty");
    const stateLoading = document.getElementById("state-loading");
    const stateError = document.getElementById("state-error");
    const stateActive = document.getElementById("state-active");
    const errorMessage = document.getElementById("error-message");
    const retryBtn = document.getElementById("retry-btn");

    // Results DOM
    const jdBanner = document.getElementById("jd-used-banner");
    const jdToggleBtn = document.getElementById("jd-toggle-btn");
    const jdTextPreview = document.getElementById("jd-text-preview");
    const runNotice = document.getElementById("run-notice");
    const resultsLeaderboard = document.getElementById("results-leaderboard");
    const resultsHeaderText = document.getElementById("results-header-text");
    const reviewToolbar = document.getElementById("review-toolbar");
    const reviewSummary = document.getElementById("review-summary");
    const regroupBtn = document.getElementById("regroup-btn");
    const exportBtn = document.getElementById("export-btn");

    // Evidence review panel
    const reviewOverlay = document.getElementById("review-overlay");
    const reviewTitle = document.getElementById("review-title");
    const reviewBand = document.getElementById("review-band");
    const reviewOpenOriginal = document.getElementById("review-open-original");
    const reviewClose = document.getElementById("review-close");
    const reviewReqList = document.getElementById("review-req-list");
    const reviewHidden = document.getElementById("review-hidden");
    const reviewDocText = document.getElementById("review-doc-text");

    // Local file cache
    let selectedFiles = [];
    let discardArmed = false;
    // Recruiter-confirmed requirements; empty means similarity-only mode
    let requirements = [];
    const MAX_REQUIREMENTS = 15;

    // The API is served from the same origin by default. To point a separately hosted
    // frontend at another backend, set window.HIREINTEL_API_BASE before this script loads.
    const API_BASE = (window.HIREINTEL_API_BASE || "").replace(/\/$/, "");
    const REQUEST_TIMEOUT_MS = 180000; // free hosting can take ~1 minute to wake up
    // Similarity differences this small are within embedding noise, so the order means little.
    const CLOSE_SCORE_SPREAD = 2;

    const ALLOWED_EXTS = ["pdf", "docx", "txt", "png", "jpg", "jpeg", "webp"];
    const SAMPLE_FILES = [
        "samples/aarav_backend_engineer.txt",
        "samples/meera_fullstack_developer.txt",
        "samples/rohan_data_analyst.txt",
        "samples/kavya_python_intern.txt",
    ];
    let limits = { max_files: 10, max_file_size_mb: 5, access_code_required: false };

    // Initialize Lucide Icons
    lucide.createIcons();
    checkServer();

    // -------------------------------------------------------------
    // Server status and limits
    // -------------------------------------------------------------
    async function checkServer() {
        setStatus("checking", "Checking server…");
        try {
            const response = await fetch(`${API_BASE}/api/config`);
            if (!response.ok) throw new Error();
            limits = await response.json();
            uploadLimits.textContent = `Supports PDF, DOCX, TXT and images (max ${limits.max_files} files, ${limits.max_file_size_mb} MB each)`;
            accessCodeGroup.style.display = limits.access_code_required ? "flex" : "none";
            setStatus("online", "Server online");
        } catch {
            setStatus("offline", "Server unreachable");
        }
    }

    function setStatus(state, text) {
        statusBadge.className = `header-badge status-${state}`;
        statusText.textContent = text;
    }

    // -------------------------------------------------------------
    // Drag & Drop File Zone Handlers
    // -------------------------------------------------------------
    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("drag-over");
    });

    ["dragleave", "dragend"].forEach(type => {
        dropZone.addEventListener(type, () => {
            dropZone.classList.remove("drag-over");
        });
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-over");
        if (e.dataTransfer.files.length > 0) {
            handleFilesSelected(e.dataTransfer.files);
        }
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFilesSelected(e.target.files);
        }
    });

    // Validate files against the same limits the server enforces
    function handleFilesSelected(files) {
        const problems = [];
        for (const file of files) {
            const ext = file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "";
            if (!ALLOWED_EXTS.includes(ext)) {
                problems.push(`"${file.name}" skipped: unsupported type${ext === "doc" ? " (re-save .doc as DOCX or PDF)" : ""}.`);
                continue;
            }
            if (file.size > limits.max_file_size_mb * 1024 * 1024) {
                problems.push(`"${file.name}" skipped: larger than ${limits.max_file_size_mb} MB.`);
                continue;
            }
            if (selectedFiles.some(f => f.name === file.name && f.size === file.size)) {
                continue;
            }
            if (selectedFiles.length >= limits.max_files) {
                problems.push(`Only ${limits.max_files} files can be analysed at once.`);
                break;
            }
            selectedFiles.push(file);
        }
        showFileWarning(problems.join(" "));
        renderFileList();
    }

    function showFileWarning(text) {
        fileWarning.textContent = text;
        fileWarning.style.display = text ? "block" : "none";
    }

    // Load the bundled synthetic job description and resumes
    sampleBtn.addEventListener("click", async () => {
        sampleBtn.disabled = true;
        try {
            const jd = await fetch("samples/sample_job_description.txt").then(r => {
                if (!r.ok) throw new Error();
                return r.text();
            });
            const files = await Promise.all(SAMPLE_FILES.map(async path => {
                const r = await fetch(path);
                if (!r.ok) throw new Error();
                return new File([await r.blob()], path.split("/").pop(), { type: "text/plain" });
            }));
            jobDescInput.value = jd.trim();
            setRequirements([], []);
            selectedFiles = [];
            handleFilesSelected(files);
        } catch {
            showFileWarning("Could not load the sample files.");
        } finally {
            sampleBtn.disabled = false;
        }
    });

    // -------------------------------------------------------------
    // Requirement extraction and editing
    // -------------------------------------------------------------
    function accessHeaders() {
        return limits.access_code_required ? { "X-Demo-Access-Code": accessCodeInput.value } : {};
    }

    extractReqBtn.addEventListener("click", async () => {
        const jdText = jobDescInput.value.trim();
        if (!jdText) {
            jobDescInput.focus();
            showFileWarning("Paste a job description first.");
            return;
        }
        showFileWarning("");
        const label = extractReqBtn.querySelector("span");
        extractReqBtn.disabled = true;
        label.textContent = "Extracting requirements…";
        try {
            const formData = new FormData();
            formData.append("job_description", jdText);
            const response = await fetch(`${API_BASE}/api/requirements`, {
                method: "POST",
                body: formData,
                headers: accessHeaders(),
            });
            if (!response.ok) throw new Error(await readError(response));
            const data = await response.json();
            setRequirements(data.requirements || [], data.not_assessable || []);
            if (!requirements.length) showFileWarning("No checkable requirements were found. Add them manually.");
        } catch (error) {
            showFileWarning(error instanceof TypeError ? "Could not reach the server." : error.message);
        } finally {
            extractReqBtn.disabled = false;
            label.textContent = "Re-extract requirements";
        }
    });

    function setRequirements(items, notAssessableItems) {
        requirements = items.slice(0, MAX_REQUIREMENTS).map(r => ({ text: String(r.text || ""), importance: r.importance === "mandatory" ? "mandatory" : "preferred" }));
        notAssessableList.innerHTML = notAssessableItems.map(item => `<li>${escapeHTML(item)}</li>`).join("");
        notAssessableCount.textContent = notAssessableItems.length;
        notAssessable.style.display = notAssessableItems.length ? "block" : "none";
        if (!items.length && !notAssessableItems.length) {
            extractReqBtn.querySelector("span").textContent = "Extract requirements to check";
        }
        renderRequirementEditor();
    }

    function renderRequirementEditor() {
        reqEditor.style.display = requirements.length || notAssessable.style.display === "block" ? "flex" : "none";
        reqList.innerHTML = "";
        requirements.forEach((req, index) => {
            const li = document.createElement("li");
            li.className = "req-item";

            const input = document.createElement("input");
            input.type = "text";
            input.className = "text-input";
            input.value = req.text;
            input.maxLength = 200;
            input.setAttribute("aria-label", `Requirement ${index + 1}`);
            input.addEventListener("input", () => { req.text = input.value; });

            const select = document.createElement("select");
            select.className = "importance-select";
            select.setAttribute("aria-label", `Importance of requirement ${index + 1}`);
            select.innerHTML = `<option value="mandatory">Mandatory</option><option value="preferred">Preferred</option>`;
            select.value = req.importance;
            select.addEventListener("change", () => { req.importance = select.value; });

            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "file-remove-btn";
            remove.setAttribute("aria-label", `Remove requirement ${index + 1}`);
            remove.innerHTML = `<i data-lucide="x"></i>`;
            remove.addEventListener("click", () => {
                requirements.splice(index, 1);
                renderRequirementEditor();
            });

            li.append(input, select, remove);
            reqList.appendChild(li);
        });
        addReqBtn.disabled = requirements.length >= MAX_REQUIREMENTS;
        lucide.createIcons();
    }

    addReqBtn.addEventListener("click", () => {
        requirements.push({ text: "", importance: "preferred" });
        renderRequirementEditor();
        const inputs = reqList.querySelectorAll("input");
        if (inputs.length) inputs[inputs.length - 1].focus();
    });

    clearReqBtn.addEventListener("click", () => setRequirements([], []));

    // Helper to dynamically set submit button text and results panel header text
    function updateUIForFileCount() {
        if (selectedFiles.length <= 1) {
            submitBtn.querySelector(".btn-text").textContent = "Analyze";
            resultsHeaderText.textContent = selectedFiles.length === 0 ? "Analysis & Leaderboard" : "Candidate Analysis";
        } else {
            submitBtn.querySelector(".btn-text").textContent = "Analyze and Rank";
            resultsHeaderText.textContent = "Leaderboard & Rankings";
        }
    }

    // Render list of files chosen
    function renderFileList() {
        fileList.innerHTML = "";

        selectedFiles.forEach((file, index) => {
            const fileItem = document.createElement("li");
            fileItem.className = "file-item";

            const infoDiv = document.createElement("div");
            infoDiv.className = "file-item-info";

            const ext = file.name.split(".").pop().toLowerCase();
            let iconName = "file-text";
            if (ext === "docx") {
                iconName = "file-code";
            } else if (["png", "jpg", "jpeg", "webp"].includes(ext)) {
                iconName = "file-image";
            }

            const icon = document.createElement("i");
            icon.setAttribute("data-lucide", iconName);
            const name = document.createElement("span");
            name.className = "file-name-truncated";
            name.title = file.name;
            name.textContent = file.name;
            infoDiv.append(icon, name);

            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "file-remove-btn";
            removeBtn.setAttribute("aria-label", `Remove ${file.name}`);
            removeBtn.innerHTML = `<i data-lucide="x"></i>`;
            removeBtn.addEventListener("click", () => removeFile(index));

            fileItem.appendChild(infoDiv);
            fileItem.appendChild(removeBtn);
            fileList.appendChild(fileItem);
        });

        lucide.createIcons();
        updateUIForFileCount();
    }

    function removeFile(index) {
        selectedFiles.splice(index, 1);
        renderFileList();
        fileInput.value = ""; // Reset input so same file can be chosen again if removed
    }

    // -------------------------------------------------------------
    // UI State Management helpers
    // -------------------------------------------------------------
    function switchState(state) {
        stateEmpty.style.display = state === "empty" ? "flex" : "none";
        stateLoading.style.display = state === "loading" ? "flex" : "none";
        stateError.style.display = state === "error" ? "flex" : "none";
        stateActive.style.display = state === "active" ? "flex" : "none";
    }

    // Turn any error response (JSON or not) into a readable message
    async function readError(response) {
        let detail = "";
        try {
            const body = await response.json();
            if (typeof body.detail === "string") {
                detail = body.detail;
            } else if (Array.isArray(body.detail)) {
                detail = body.detail.map(d => d.msg || "").filter(Boolean).join("; ");
            }
        } catch {
            // Not JSON, e.g. an HTML error page from the hosting proxy
        }
        if (detail) return detail;
        if (response.status === 413) return "Upload is too large.";
        if (response.status === 429) return "Too many requests. Please wait and try again.";
        if (response.status >= 500) return `The server had a problem (HTTP ${response.status}). Please try again shortly.`;
        return `Request failed (HTTP ${response.status}).`;
    }

    // -------------------------------------------------------------
    // Form Submission & API Fetching
    // -------------------------------------------------------------
    matchForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        if (selectedFiles.length === 0) {
            showFileWarning("Please add at least one resume, or load the samples.");
            return;
        }

        const jdText = jobDescInput.value.trim();
        if (!jdText) {
            jobDescInput.focus();
            showFileWarning("Please paste a job description or a job title.");
            return;
        }
        const confirmed = requirements
            .map(r => ({ text: r.text.trim(), importance: r.importance }))
            .filter(r => r.text);
        // A new run replaces the current review, so never discard unexported changes silently.
        if (unexportedChanges && !discardArmed) {
            discardArmed = true;
            showFileWarning("Your review changes have not been exported. Export them first, or press Analyze again to discard them.");
            return;
        }
        discardArmed = false;
        showFileWarning("");
        const filesForRun = new Map(selectedFiles.map(file => [file.name, file]));

        const formData = new FormData();
        formData.append("job_description", jdText);
        if (confirmed.length) {
            formData.append("requirements", JSON.stringify(confirmed));
        }
        selectedFiles.forEach(file => formData.append("files", file));

        const headers = accessHeaders();

        switchState("loading");
        submitBtn.disabled = true;
        submitBtn.querySelector(".btn-text").textContent = selectedFiles.length <= 1 ? "Analyzing..." : "Analyzing & Ranking...";

        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

        try {
            const response = await fetch(`${API_BASE}/api/match`, {
                method: "POST",
                body: formData,
                headers,
                signal: controller.signal,
            });

            if (!response.ok) {
                throw new Error(await readError(response));
            }

            const data = await response.json();
            submittedFiles = filesForRun;
            overrides = new Map();
            groupByReviewed = false;
            unexportedChanges = false;
            renderResults(data);
            switchState("active");
            setStatus("online", "Server online");

        } catch (error) {
            console.error("API error:", error);
            if (error.name === "AbortError") {
                errorMessage.textContent = "The request timed out. The server may be waking up; please try again.";
            } else if (error instanceof TypeError) {
                errorMessage.textContent = "Could not reach the server. Please check your connection and try again.";
                setStatus("offline", "Server unreachable");
            } else {
                errorMessage.textContent = error.message;
            }
            switchState("error");
        } finally {
            clearTimeout(timer);
            submitBtn.disabled = false;
            updateUIForFileCount();
        }
    });

    retryBtn.addEventListener("click", () => {
        submitBtn.click();
    });

    // -------------------------------------------------------------
    // Rendering Results List
    // -------------------------------------------------------------
    function listItems(items, emptyText) {
        const safe = Array.isArray(items) ? items : [];
        return safe.map(item => `<li>${escapeHTML(item)}</li>`).join("") || `<li>${escapeHTML(emptyText)}</li>`;
    }

    function renderNotice(el, messages) {
        if (!messages.length) {
            el.style.display = "none";
            return;
        }
        el.innerHTML = messages.map(m => `<p><i data-lucide="alert-triangle"></i><span>${escapeHTML(m)}</span></p>`).join("");
        el.style.display = "block";
    }

    function errorCard(candidate) {
        const card = document.createElement("div");
        card.className = "candidate-card error-card";
        const filename = escapeHTML(candidate.filename);
        card.innerHTML = `
            <div class="card-header-main">
                <div class="candidate-meta">
                    <span class="rank-badge rank-none" aria-label="Not ranked">–</span>
                    <span class="candidate-title" title="${filename}">${filename}</span>
                </div>
                <div class="score-badge-container">
                    <span class="score-badge error-badge">Could not process</span>
                    <i data-lucide="chevron-down" class="card-toggle-icon"></i>
                </div>
            </div>
            <div class="card-details">
                <p class="card-error-text">
                    <i data-lucide="alert-circle"></i>
                    <span>${escapeHTML(candidate.error_message)}</span>
                </p>
            </div>
        `;
        attachToggle(card);
        return card;
    }

    function warningsHtml(candidate) {
        const warnings = Array.isArray(candidate.warnings) ? candidate.warnings : [];
        return warnings.length
            ? `<div class="card-warnings">${warnings.map(w => `<p><i data-lucide="alert-triangle"></i><span>${escapeHTML(w)}</span></p>`).join("")}</div>`
            : "";
    }

    function rawTextSection(candidate) {
        return `
            <div class="card-actions">
                <button type="button" class="toggle-raw-btn">
                    <i data-lucide="terminal"></i>
                    <span>View Extracted Text</span>
                </button>
            </div>
            <pre class="raw-text-wrapper">${escapeHTML(candidate.raw_text)}</pre>
        `;
    }

    function attachRawToggle(card) {
        const toggleRawBtn = card.querySelector(".toggle-raw-btn");
        const rawTextWrapper = card.querySelector(".raw-text-wrapper");
        toggleRawBtn.addEventListener("click", (e) => {
            e.stopPropagation(); // Avoid triggering card accordion collapse
            const isRawOpen = rawTextWrapper.style.display === "block";
            rawTextWrapper.style.display = isRawOpen ? "none" : "block";
            toggleRawBtn.querySelector("span").textContent = isRawOpen ? "View Extracted Text" : "Hide Extracted Text";
        });
    }

    // -------------------------------------------------------------
    // Requirement mode: candidates grouped by evidence band
    // -------------------------------------------------------------
    const STATE_INFO = {
        supported: { icon: "circle-check", label: "Evidence found", cls: "state-supported" },
        needs_review: { icon: "circle-help", label: "Needs review", cls: "state-review" },
        no_evidence: { icon: "circle-minus", label: "No evidence found", cls: "state-none" },
    };
    const BAND_CLASS = { B1: "band-1", B0: "band-1", B2: "band-2", B3: "band-3", B4: "band-4" };
    // Same rules and labels as the server (app/services/requirements.py), so a recruiter's
    // overrides move a candidate between bands exactly as the AI's states would.
    const BAND_LABELS = {
        B1: "All mandatory requirements supported",
        B2: "Mandatory requirements need review",
        B3: "No evidence for 1 mandatory requirement",
        B4: "No evidence for 2+ mandatory requirements",
        B0: "No mandatory requirements set",
    };
    const BAND_ORDER = { B1: 0, B0: 0, B2: 1, B3: 2, B4: 3 };
    const OVERRIDE_REASONS = {
        evidence_elsewhere: "Evidence is elsewhere in the resume",
        equivalent: "Equivalent skill or experience",
        not_equivalent: "Quoted evidence is not equivalent",
        ai_misread: "The AI misread the resume",
        confirmed_with_candidate: "Confirmed with the candidate",
        other: "Other (explain in the note)",
    };

    // The option label without its hint, e.g. "Other" rather than "Other (explain in the note)"
    function reasonLabel(code) {
        return (OVERRIDE_REASONS[code] || "").replace(/ \(.*\)$/, "");
    }

    // Recruiter review of the current run. Kept in this tab only: nothing is sent to the server.
    let lastRun = null;
    let submittedFiles = new Map(); // filename -> File, for "Open original file"
    let overrides = new Map(); // filename -> Map(requirement id -> {state, reason, note, at})
    let groupByReviewed = false;
    let unexportedChanges = false;

    function overridesFor(filename) {
        if (!overrides.has(filename)) overrides.set(filename, new Map());
        return overrides.get(filename);
    }

    // Requirements with the recruiter's overrides applied; the AI's state is kept as aiState.
    function effectiveRequirements(candidate) {
        const own = overrides.get(candidate.filename) || new Map();
        return (candidate.assessment.requirements || []).map(r => {
            const override = own.get(r.id) || null;
            return { ...r, aiState: r.state, state: override ? override.state : r.state, override };
        });
    }

    function bandOf(reqs) {
        const mandatory = reqs.filter(r => r.importance === "mandatory");
        if (!mandatory.length) return "B0";
        const missing = mandatory.filter(r => r.state === "no_evidence").length;
        if (missing >= 2) return "B4";
        if (missing === 1) return "B3";
        return mandatory.some(r => r.state === "needs_review") ? "B2" : "B1";
    }

    function countsOf(reqs) {
        const counts = { supported: 0, needs_review: 0, no_evidence: 0 };
        reqs.forEach(r => { if (r.state in counts) counts[r.state] += 1; });
        return counts;
    }

    function groupOf(candidate) {
        if (candidate.status === "error") return "error";
        if (!candidate.assessment) return "unassessed";
        return groupByReviewed ? bandOf(effectiveRequirements(candidate)) : candidate.assessment.band.code;
    }

    // Mirrors requirement_sort_key on the server, using the reviewed states
    function reviewedSortKey(candidate) {
        if (candidate.status === "error") return [2, 0, 0, 0, candidate.filename];
        if (!candidate.assessment) return [1, 0, 0, 0, candidate.filename];
        const reqs = effectiveRequirements(candidate);
        const preferred = reqs.filter(r => r.importance === "preferred" && r.state === "supported").length;
        const score = typeof candidate.similarity_score === "number" ? candidate.similarity_score : -1;
        return [0, BAND_ORDER[bandOf(reqs)], -preferred, -score, candidate.filename];
    }

    function compareKeys(a, b) {
        for (let i = 0; i < a.length; i++) {
            if (a[i] < b[i]) return -1;
            if (a[i] > b[i]) return 1;
        }
        return 0;
    }

    function requirementRows(reqs) {
        return reqs.map(r => {
            const info = STATE_INFO[r.state] || STATE_INFO.needs_review;
            const quotes = (Array.isArray(r.quotes) ? r.quotes : []).map(q => `
                <blockquote class="evidence-quote ${q.verified ? "" : "unverified"}">
                    “${escapeHTML(q.text)}”
                    <span class="quote-tag">${q.verified ? "found in resume" : "not found in resume text"}</span>
                </blockquote>`).join("");
            return `
                <li class="req-row ${info.cls}">
                    <i data-lucide="${info.icon}" class="req-state-icon" aria-hidden="true"></i>
                    <div class="req-body">
                        <div class="req-title">
                            <span>${escapeHTML(r.text)}</span>
                            <span class="importance-tag ${r.importance === "mandatory" ? "mandatory" : ""}">${escapeHTML(r.importance)}</span>
                        </div>
                        <div class="req-state-label">${info.label}${r.override ? ` <span class="reviewed-tag">reviewed</span>` : ""}</div>
                        ${overrideNote(r)}
                        ${r.note ? `<p class="req-note">${escapeHTML(r.note)}</p>` : ""}
                        ${quotes}
                    </div>
                </li>`;
        }).join("");
    }

    function overrideNote(r) {
        if (!r.override) return "";
        const ai = (STATE_INFO[r.aiState] || STATE_INFO.needs_review).label;
        const note = r.override.note ? `: ${escapeHTML(r.override.note)}` : "";
        return `<p class="override-note">Changed by reviewer from “${ai}”. ${escapeHTML(reasonLabel(r.override.reason))}${note}</p>`;
    }

    function renderRequirementResults(results) {
        const openFilename = document.querySelector(".candidate-card.open")?.dataset.filename;
        resultsLeaderboard.innerHTML = "";

        const notices = ["Candidates are grouped by the evidence found for mandatory requirements. Nobody is rejected automatically: review every group, including the lower ones."];
        if (results.length && results.every(r => r.status === "error")) {
            notices.push("None of the files could be processed. See the details on each card.");
        }
        renderNotice(runNotice, notices);

        const ordered = groupByReviewed
            ? [...results].sort((a, b) => compareKeys(reviewedSortKey(a), reviewedSortKey(b)))
            : results;
        let currentGroup = null;
        ordered.forEach(candidate => {
            const group = groupOf(candidate);
            if (group !== currentGroup) {
                currentGroup = group;
                const label = group === "error" ? "Could not be processed"
                    : group === "unassessed" ? "Not assessed (AI unavailable)"
                    : `${group} · ${BAND_LABELS[group]}${groupByReviewed ? " (after review)" : ""}`;
                const count = ordered.filter(r => groupOf(r) === group).length;
                const header = document.createElement("h3");
                header.className = `band-header ${BAND_CLASS[group] || ""}`;
                header.textContent = `${label} (${count})`;
                resultsLeaderboard.appendChild(header);
            }

            if (candidate.status === "error") {
                resultsLeaderboard.appendChild(errorCard(candidate));
                return;
            }

            const assessment = candidate.assessment;
            const card = document.createElement("div");
            card.className = "candidate-card";
            card.dataset.filename = candidate.filename;
            const filename = escapeHTML(candidate.filename);
            const score = typeof candidate.similarity_score === "number" ? `${candidate.similarity_score} similarity` : "similarity unavailable";

            let headerRight;
            let details;
            if (assessment) {
                const reqs = effectiveRequirements(candidate);
                const c = countsOf(reqs);
                const reviewedBand = bandOf(reqs);
                const bandChip = reviewedBand !== assessment.band.code
                    ? `<span class="band-chip ${BAND_CLASS[reviewedBand]}" title="Band after the reviewer's changes">${escapeHTML(assessment.band.code)} → ${reviewedBand}</span>`
                    : "";
                headerRight = `
                    ${bandChip}
                    <span class="evidence-counts" title="Requirements with evidence found / needing review / with no evidence found">
                        <span class="state-supported">✓ ${c.supported}</span>
                        <span class="state-review">? ${c.needs_review}</span>
                        <span class="state-none">– ${c.no_evidence}</span>
                    </span>
                    <span class="similarity-small" title="Cosine similarity between the job description and resume (0-100). Not a probability of fit.">${score}</span>`;
                details = `
                    <p class="candidate-summary">${escapeHTML(assessment.summary)}</p>
                    <div class="card-actions">
                        <button type="button" class="secondary-btn review-btn">
                            <i data-lucide="file-search"></i>
                            <span>Review evidence</span>
                        </button>
                    </div>
                    <ul class="req-results">${requirementRows(reqs)}</ul>
                    ${assessment.points_to_verify && assessment.points_to_verify.length ? `
                        <div class="recommendations-section">
                            <h4>Points to Verify with the Candidate</h4>
                            <ul class="rec-list">${listItems(assessment.points_to_verify, "")}</ul>
                        </div>` : ""}
                    <p class="ai-footnote">Assessed by ${escapeHTML(assessment.model)}. Quotes are checked against the extracted text; a found quote shows the words exist, not that the AI interpreted them correctly.</p>`;
            } else {
                headerRight = `<span class="score-badge unavailable-badge">Not assessed</span><span class="similarity-small">${score}</span>`;
                details = `<p class="candidate-summary">The requirement assessment is unavailable for this resume right now.</p>`;
            }

            card.innerHTML = `
                <div class="card-header-main">
                    <div class="candidate-meta">
                        <span class="candidate-title" title="${filename}">${filename}</span>
                    </div>
                    <div class="score-badge-container">
                        ${headerRight}
                        <i data-lucide="chevron-down" class="card-toggle-icon"></i>
                    </div>
                </div>
                <div class="card-details">
                    ${warningsHtml(candidate)}
                    ${hiddenTextHtml(candidate)}
                    ${details}
                    ${rawTextSection(candidate)}
                </div>
            `;
            if (candidate.filename === openFilename) card.classList.add("open");
            attachToggle(card);
            attachRawToggle(card);
            const reviewBtn = card.querySelector(".review-btn");
            if (reviewBtn) reviewBtn.addEventListener("click", () => openReview(candidate, reviewBtn));
            resultsLeaderboard.appendChild(card);
        });
        renderReviewToolbar(results);
        lucide.createIcons();
    }

    function renderReviewToolbar(results) {
        const assessed = results.filter(r => r.status !== "error" && r.assessment);
        const changes = assessed.reduce((n, r) => n + (overrides.get(r.filename)?.size || 0), 0);
        const moved = assessed.filter(r => bandOf(effectiveRequirements(r)) !== r.assessment.band.code).length;
        reviewToolbar.style.display = "flex";
        reviewSummary.textContent = changes
            ? `${changes} requirement${changes === 1 ? "" : "s"} changed by review; ${moved} candidate${moved === 1 ? "" : "s"} moved band.${unexportedChanges ? " Not exported yet." : ""}`
            : "No review changes yet. Open a candidate and choose “Review evidence”.";
        regroupBtn.style.display = moved || groupByReviewed ? "inline-flex" : "none";
        regroupBtn.textContent = groupByReviewed ? "Group by AI bands" : "Group by reviewed bands";
    }

    regroupBtn.addEventListener("click", () => {
        groupByReviewed = !groupByReviewed;
        renderRequirementResults(lastRun.results);
    });

    // Hidden text the parser left out, shown so the recruiter can judge it
    function hiddenTextHtml(candidate) {
        const items = Array.isArray(candidate.hidden_text) ? candidate.hidden_text : [];
        if (!items.length) return "";
        const total = candidate.hidden_text_count || items.length;
        const more = total > items.length ? `<p class="hidden-more">…and ${total - items.length} more.</p>` : "";
        return `
            <details class="hidden-text">
                <summary><i data-lucide="eye-off"></i><span>Hidden text left out of the analysis (${total})</span></summary>
                <ul>${items.map(t => `<li><code>${escapeHTML(t)}</code></li>`).join("")}</ul>
                ${more}
            </details>`;
    }

    // -------------------------------------------------------------
    // Evidence review: requirements beside the extracted text
    // -------------------------------------------------------------
    let reviewCandidate = null;
    let reviewReturnFocus = null;

    function openReview(candidate, returnFocus) {
        reviewCandidate = candidate;
        reviewReturnFocus = returnFocus;
        reviewTitle.textContent = candidate.filename;
        reviewOpenOriginal.style.display = submittedFiles.has(candidate.filename) ? "inline-flex" : "none";
        reviewHidden.innerHTML = hiddenTextHtml(candidate);
        renderReview();
        reviewOverlay.hidden = false;
        document.body.classList.add("review-open");
        reviewDocText.scrollTop = 0;
        reviewClose.focus();
    }

    function closeReview() {
        reviewOverlay.hidden = true;
        document.body.classList.remove("review-open");
        reviewCandidate = null;
        if (reviewReturnFocus && document.contains(reviewReturnFocus)) reviewReturnFocus.focus();
    }

    reviewClose.addEventListener("click", closeReview);
    reviewOverlay.addEventListener("click", e => { if (e.target === reviewOverlay) closeReview(); });
    document.addEventListener("keydown", e => {
        if (e.key === "Escape" && !reviewOverlay.hidden) closeReview();
    });

    reviewOpenOriginal.addEventListener("click", () => {
        const file = reviewCandidate && submittedFiles.get(reviewCandidate.filename);
        if (!file) return;
        // The file is shown from this browser's memory; it is not uploaded again.
        const url = URL.createObjectURL(file);
        window.open(url, "_blank", "noopener");
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    });

    function renderReview() {
        const candidate = reviewCandidate;
        const reqs = effectiveRequirements(candidate);
        const aiBand = candidate.assessment.band.code;
        const band = bandOf(reqs);
        reviewBand.className = `review-band ${BAND_CLASS[band] || ""}`;
        reviewBand.textContent = band === aiBand
            ? `${band} · ${BAND_LABELS[band]}`
            : `${band} · ${BAND_LABELS[band]} (AI: ${aiBand})`;

        reviewReqList.innerHTML = "";
        reqs.forEach(r => reviewReqList.appendChild(reviewRow(r)));
        reviewDocText.innerHTML = highlightedText(candidate.raw_text || "", reqs);
        reviewDocText.querySelectorAll("mark").forEach(mark => {
            mark.addEventListener("click", () => {
                const row = reviewReqList.querySelector(`[data-req="${mark.dataset.req.split(" ")[0]}"]`);
                if (row) flash(row);
            });
        });
        lucide.createIcons();
    }

    function reviewRow(r) {
        const info = STATE_INFO[r.state] || STATE_INFO.needs_review;
        const li = document.createElement("li");
        li.className = `req-row ${info.cls}`;
        li.dataset.req = r.id;
        const quotes = (Array.isArray(r.quotes) ? r.quotes : []).map((q, qi) => q.verified && q.spans && q.spans.length
            ? `<button type="button" class="evidence-quote quote-link" data-q="${escapeHTML(r.id)}-${qi}">
                    “${escapeHTML(q.text)}”<span class="quote-tag">found in resume · show in text</span></button>`
            : `<blockquote class="evidence-quote unverified">“${escapeHTML(q.text)}”
                    <span class="quote-tag">not found in resume text</span></blockquote>`).join("");
        const stateOptions = Object.entries(STATE_INFO)
            .map(([value, s]) => `<option value="${value}" ${value === r.state ? "selected" : ""}>${s.label}</option>`).join("");
        const reasonOptions = Object.entries(OVERRIDE_REASONS)
            .map(([value, label]) => `<option value="${value}" ${r.override && r.override.reason === value ? "selected" : ""}>${label}</option>`).join("");

        li.innerHTML = `
            <i data-lucide="${info.icon}" class="req-state-icon" aria-hidden="true"></i>
            <div class="req-body">
                <div class="req-title">
                    <span>${escapeHTML(r.id)} · ${escapeHTML(r.text)}</span>
                    <span class="importance-tag ${r.importance === "mandatory" ? "mandatory" : ""}">${escapeHTML(r.importance)}</span>
                </div>
                <div class="req-state-label">${info.label}${r.override ? ` <span class="reviewed-tag">reviewed</span>` : ""}</div>
                ${overrideNote(r)}
                ${r.note ? `<p class="req-note">AI: ${escapeHTML(r.note)}</p>` : ""}
                ${quotes}
                <div class="override-actions">
                    <button type="button" class="link-btn ov-edit">${r.override ? "Edit review" : "Change state"}</button>
                    ${r.override ? `<button type="button" class="link-btn ov-undo">Undo, use the AI's state</button>` : ""}
                </div>
                <form class="override-form" hidden>
                    <label>New state <select class="ov-state">${stateOptions}</select></label>
                    <label>Reason <select class="ov-reason" required><option value="">Choose a reason…</option>${reasonOptions}</select></label>
                    <label>Note <textarea class="ov-note" rows="2" maxlength="300" placeholder="Optional, unless the reason is Other">${r.override ? escapeHTML(r.override.note) : ""}</textarea></label>
                    <div class="override-buttons">
                        <button type="submit" class="secondary-btn ov-save">Save</button>
                        <button type="button" class="link-btn ov-cancel">Cancel</button>
                    </div>
                </form>
            </div>`;

        const form = li.querySelector(".override-form");
        const state = li.querySelector(".ov-state");
        const reason = li.querySelector(".ov-reason");
        const note = li.querySelector(".ov-note");
        const save = li.querySelector(".ov-save");
        const validate = () => {
            save.disabled = !reason.value || (reason.value === "other" && !note.value.trim());
        };
        [state, reason, note].forEach(el => el.addEventListener("input", validate));
        validate();

        li.querySelector(".ov-edit").addEventListener("click", () => {
            form.hidden = false;
            state.focus();
        });
        li.querySelector(".ov-cancel").addEventListener("click", () => { form.hidden = true; });
        form.addEventListener("submit", e => {
            e.preventDefault();
            if (save.disabled) return;
            overridesFor(reviewCandidate.filename).set(r.id, {
                state: state.value, reason: reason.value, note: note.value.trim(), at: new Date().toISOString(),
            });
            reviewChanged(r.id);
        });
        const undo = li.querySelector(".ov-undo");
        if (undo) undo.addEventListener("click", () => {
            overridesFor(reviewCandidate.filename).delete(r.id);
            reviewChanged(r.id);
        });
        li.querySelectorAll(".quote-link").forEach(btn => {
            btn.addEventListener("click", () => {
                const mark = reviewDocText.querySelector(`mark[data-q~="${btn.dataset.q}"]`);
                if (mark) flash(mark);
            });
        });
        return li;
    }

    function reviewChanged(reqId) {
        unexportedChanges = true;
        renderReview();
        renderRequirementResults(lastRun.results);
        const row = reviewReqList.querySelector(`[data-req="${reqId}"] .ov-edit`);
        if (row) row.focus();
    }

    function flash(el) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        el.classList.remove("flash");
        void el.offsetWidth; // restart the animation
        el.classList.add("flash");
    }

    // Wraps verified quote spans in <mark>. Offsets come from Python and count code points,
    // so the text is sliced by code point, not by UTF-16 unit (emoji would shift the marks).
    function highlightedText(text, reqs) {
        const chars = Array.from(text);
        const marks = [];
        reqs.forEach(r => (Array.isArray(r.quotes) ? r.quotes : []).forEach((q, qi) => {
            if (!q.verified || !Array.isArray(q.spans)) return;
            q.spans.forEach(span => {
                const [start, end] = Array.isArray(span) ? span : [];
                if (Number.isInteger(start) && Number.isInteger(end) && start >= 0 && start < end && end <= chars.length) {
                    marks.push({ start, end, id: `${r.id}-${qi}`, req: r.id });
                }
            });
        }));
        const points = [...new Set([0, chars.length, ...marks.flatMap(m => [m.start, m.end])])].sort((a, b) => a - b);
        let html = "";
        for (let i = 0; i < points.length - 1; i++) {
            const [a, b] = [points[i], points[i + 1]];
            const chunk = escapeHTML(chars.slice(a, b).join(""));
            const active = marks.filter(m => m.start <= a && m.end >= b);
            html += active.length
                ? `<mark class="ev-mark" data-q="${active.map(m => m.id).join(" ")}" data-req="${[...new Set(active.map(m => m.req))].join(" ")}">${chunk}</mark>`
                : chunk;
        }
        return html;
    }

    // -------------------------------------------------------------
    // Export the review as CSV
    // -------------------------------------------------------------
    function csvCell(value) {
        let text = value === null || value === undefined ? "" : String(value);
        // Cells starting with these are run as formulas by spreadsheet apps (CSV injection).
        if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
        return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    }

    exportBtn.addEventListener("click", () => {
        if (!lastRun) return;
        const exportedAt = new Date().toISOString();
        const header = ["run_id", "exported_at", "filename", "status", "ai_band", "reviewed_band", "requirement_id", "requirement",
            "importance", "ai_state", "final_state", "changed_by_reviewer", "reason", "reviewer_note", "verified_quotes", "model"];
        const rows = [header];
        lastRun.results.forEach(candidate => {
            const base = [lastRun.run_id, exportedAt, candidate.filename, candidate.status];
            if (candidate.status === "error" || !candidate.assessment) {
                rows.push([...base, "", "", "", "", "", "", "", "", "", "", "", candidate.error_message || "not assessed"]);
                return;
            }
            const reqs = effectiveRequirements(candidate);
            const reviewedBand = bandOf(reqs);
            reqs.forEach(r => rows.push([
                ...base, candidate.assessment.band.code, reviewedBand, r.id, r.text, r.importance, r.aiState, r.state,
                r.override ? "yes" : "no", r.override ? reasonLabel(r.override.reason) : "", r.override ? r.override.note : "",
                (r.quotes || []).filter(q => q.verified).map(q => q.text).join(" | "), candidate.assessment.model,
            ]));
        });
        // A byte-order mark makes Excel read the file as UTF-8.
        const csv = "﻿" + rows.map(row => row.map(csvCell).join(",")).join("\r\n");
        const link = document.createElement("a");
        link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
        link.download = `hireintel-review-${lastRun.run_id}.csv`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 10000);
        unexportedChanges = false;
        renderReviewToolbar(lastRun.results);
    });

    window.addEventListener("beforeunload", e => {
        if (unexportedChanges) {
            e.preventDefault();
            e.returnValue = "";
        }
    });

    function renderResults(data) {
        resultsLeaderboard.innerHTML = "";
        jdTextPreview.style.display = "none";
        jdToggleBtn.classList.remove("open");
        jdToggleBtn.querySelector("span").textContent = "Show generated details";

        if (data.is_job_description_expanded) {
            jdBanner.style.display = "flex";
            jdTextPreview.textContent = data.job_description_used;
        } else {
            jdBanner.style.display = "none";
        }

        const results = Array.isArray(data.results) ? data.results : [];
        lastRun = { ...data, results };
        if (data.mode === "requirements") {
            renderRequirementResults(results);
            return;
        }
        reviewToolbar.style.display = "none";

        const notices = [];
        if (data.scoring_available === false) {
            notices.push("Similarity scoring is unavailable right now, so candidates are not ranked. AI analysis is shown where available.");
        }
        if (results.length && results.every(r => r.status === "error")) {
            notices.push("None of the files could be processed. See the details on each card.");
        }
        const scores = results.map(r => r.similarity_score).filter(s => typeof s === "number");
        const spread = scores.length > 1 ? Math.max(...scores) - Math.min(...scores) : null;
        if (spread !== null && spread <= CLOSE_SCORE_SPREAD) {
            notices.push(`All similarity scores are within ${spread.toFixed(1)} points of each other, so the ranking is not meaningful. Compare the analyses instead.`);
        }
        renderNotice(runNotice, notices);

        // Equal scores share a rank (1, 2, 2, 4), so ties are not presented as an order.
        const rankOf = score => 1 + scores.filter(s => s > score).length;
        results.forEach(candidate => {
            if (candidate.status === "error") {
                resultsLeaderboard.appendChild(errorCard(candidate));
                return;
            }

            const card = document.createElement("div");
            card.className = "candidate-card";
            const filename = escapeHTML(candidate.filename);
            const score = typeof candidate.similarity_score === "number" ? candidate.similarity_score : null;
            let scoreBadge;
            let rankBadge;
            if (score === null) {
                scoreBadge = `<span class="score-badge unavailable-badge" title="The similarity score could not be computed for this resume.">Score unavailable</span>`;
                rankBadge = `<span class="rank-badge rank-none" aria-label="Not ranked">–</span>`;
            } else {
                const rank = rankOf(score);
                let matchClass = "low-match";
                if (score >= 75) matchClass = "high-match";
                else if (score >= 50) matchClass = "med-match";
                scoreBadge = `<span class="score-badge ${matchClass}" title="Cosine similarity between the job description and resume embeddings (0-100). Not a probability of fit.">${score} similarity</span>`;
                const tied = scores.filter(s => s === score).length > 1;
                rankBadge = `<span class="rank-badge" ${tied ? `title="Tied with another resume"` : ""}>${tied ? "=" : ""}${rank}</span>`;
            }

            const analysis = candidate.analysis;
            const analysisHtml = analysis
                ? `
                    <p class="candidate-summary">${escapeHTML(analysis.summary) || "No summary generated."}</p>
                    <div class="analysis-grid">
                        <div class="analysis-col">
                            <div class="analysis-col-title strengths-title">
                                <i data-lucide="check-circle2"></i>
                                <span>Evidence of Strengths</span>
                            </div>
                            <ul class="analysis-list strengths-list">${listItems(analysis.strengths, "No strengths identified.")}</ul>
                        </div>
                        <div class="analysis-col">
                            <div class="analysis-col-title gaps-title">
                                <i data-lucide="alert-circle"></i>
                                <span>No Evidence Found For</span>
                            </div>
                            <ul class="analysis-list gaps-list">${listItems(analysis.gaps, "No gaps identified.")}</ul>
                        </div>
                    </div>
                    <div class="recommendations-section">
                        <h4>Points to Verify with the Candidate</h4>
                        <ul class="rec-list">${listItems(analysis.recommendations, "Nothing specific to verify.")}</ul>
                    </div>
                    ${analysis.match_explanation ? `<p class="match-explanation">${escapeHTML(analysis.match_explanation)}</p>` : ""}
                    <p class="ai-footnote">AI-generated by ${escapeHTML(analysis.model)}. Check against the resume before relying on it.</p>
                `
                : `<p class="candidate-summary">AI analysis is unavailable for this resume right now.</p>`;

            card.innerHTML = `
                <div class="card-header-main">
                    <div class="candidate-meta">
                        ${rankBadge}
                        <span class="candidate-title" title="${filename}">${filename}</span>
                    </div>
                    <div class="score-badge-container">
                        ${scoreBadge}
                        <i data-lucide="chevron-down" class="card-toggle-icon"></i>
                    </div>
                </div>

                <div class="card-details">
                    ${warningsHtml(candidate)}
                    ${hiddenTextHtml(candidate)}
                    ${analysisHtml}
                    ${rawTextSection(candidate)}
                </div>
            `;

            attachToggle(card);
            attachRawToggle(card);
            resultsLeaderboard.appendChild(card);
        });

        lucide.createIcons();
    }

    // Accordion: opening one card closes the others
    function attachToggle(card) {
        const header = card.querySelector(".card-header-main");
        header.addEventListener("click", () => {
            const isOpen = card.classList.contains("open");
            document.querySelectorAll(".candidate-card").forEach(c => c.classList.remove("open"));
            if (!isOpen) card.classList.add("open");
        });
    }

    // Toggle job description expansion banner
    jdToggleBtn.addEventListener("click", () => {
        const isClosed = jdTextPreview.style.display === "none";
        jdTextPreview.style.display = isClosed ? "block" : "none";
        jdToggleBtn.classList.toggle("open", isClosed);
        jdToggleBtn.querySelector("span").textContent = isClosed ? "Hide generated details" : "Show generated details";
    });

    // Escape any server or model value before inserting it as HTML
    function escapeHTML(value) {
        if (value === null || value === undefined) return "";
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
});
