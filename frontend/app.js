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

    // Local file cache
    let selectedFiles = [];
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
        showFileWarning("");

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

    function requirementRows(requirements) {
        return requirements.map(r => {
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
                        <div class="req-state-label">${info.label}</div>
                        ${r.note ? `<p class="req-note">${escapeHTML(r.note)}</p>` : ""}
                        ${quotes}
                    </div>
                </li>`;
        }).join("");
    }

    function renderRequirementResults(data, results) {
        const notices = ["Candidates are grouped by the evidence found for mandatory requirements. Nobody is rejected automatically: review every group, including the lower ones."];
        if (results.length && results.every(r => r.status === "error")) {
            notices.push("None of the files could be processed. See the details on each card.");
        }
        renderNotice(runNotice, notices);

        let currentGroup = null;
        results.forEach(candidate => {
            const assessment = candidate.assessment;
            const group = candidate.status === "error" ? "error" : assessment ? assessment.band.code : "unassessed";
            if (group !== currentGroup) {
                currentGroup = group;
                const label = group === "error" ? "Could not be processed"
                    : group === "unassessed" ? "Not assessed (AI unavailable)"
                    : `${group} · ${assessment.band.label}`;
                const count = results.filter(r => (r.status === "error" ? "error" : r.assessment ? r.assessment.band.code : "unassessed") === group).length;
                const header = document.createElement("h3");
                header.className = `band-header ${BAND_CLASS[group] || ""}`;
                header.textContent = `${label} (${count})`;
                resultsLeaderboard.appendChild(header);
            }

            if (candidate.status === "error") {
                resultsLeaderboard.appendChild(errorCard(candidate));
                return;
            }

            const card = document.createElement("div");
            card.className = "candidate-card";
            const filename = escapeHTML(candidate.filename);
            const score = typeof candidate.similarity_score === "number" ? `${candidate.similarity_score} similarity` : "similarity unavailable";

            let headerRight;
            let details;
            if (assessment) {
                const c = assessment.counts || {};
                headerRight = `
                    <span class="evidence-counts" title="Requirements with evidence found / needing review / with no evidence found">
                        <span class="state-supported">✓ ${c.supported || 0}</span>
                        <span class="state-review">? ${c.needs_review || 0}</span>
                        <span class="state-none">– ${c.no_evidence || 0}</span>
                    </span>
                    <span class="similarity-small" title="Cosine similarity between the job description and resume (0-100). Not a probability of fit.">${score}</span>`;
                details = `
                    <p class="candidate-summary">${escapeHTML(assessment.summary)}</p>
                    <ul class="req-results">${requirementRows(assessment.requirements || [])}</ul>
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
                    ${details}
                    ${rawTextSection(candidate)}
                </div>
            `;
            attachToggle(card);
            attachRawToggle(card);
            resultsLeaderboard.appendChild(card);
        });
        lucide.createIcons();
    }

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
        if (data.mode === "requirements") {
            renderRequirementResults(data, results);
            return;
        }

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
