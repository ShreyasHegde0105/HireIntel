document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const matchForm = document.getElementById("match-form");
    const jobDescInput = document.getElementById("job-desc-input");
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const fileList = document.getElementById("file-list");
    const submitBtn = document.getElementById("submit-btn");
    
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
    const resultsLeaderboard = document.getElementById("results-leaderboard");
    const resultsHeaderText = document.getElementById("results-header-text");

    // Local file cache
    let selectedFiles = [];

    // Backend Endpoint
    const API_URL = "http://127.0.0.1:8000/api/match";

    // Initialize Lucide Icons
    lucide.createIcons();

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

    // Process and validate files
    function handleFilesSelected(files) {
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            const ext = file.name.split('.').pop().toLowerCase();
            
            // Check file type
            if (ext !== 'pdf' && ext !== 'docx') {
                alert(`File "${file.name}" ignored. Only PDF and DOCX documents are supported.`);
                continue;
            }
            
            // Avoid duplicate additions
            const isDuplicate = selectedFiles.some(f => f.name === file.name && f.size === file.size);
            if (!isDuplicate) {
                selectedFiles.push(file);
            }
        }
        renderFileList();
    }

    // Helper to dynamically set submit button text and results panel header text
    function updateUIForFileCount() {
        if (selectedFiles.length === 0) {
            submitBtn.querySelector(".btn-text").textContent = "Analyze";
            resultsHeaderText.textContent = "Analysis & Leaderboard";
        } else if (selectedFiles.length === 1) {
            submitBtn.querySelector(".btn-text").textContent = "Analyze";
            resultsHeaderText.textContent = "Candidate Analysis";
        } else {
            submitBtn.querySelector(".btn-text").textContent = "Analyze and Rank";
            resultsHeaderText.textContent = "Leaderboard & Rankings";
        }
    }

    // Render list of files chosen
    function renderFileList() {
        fileList.innerHTML = "";
        
        if (selectedFiles.length === 0) {
            updateUIForFileCount();
            return;
        }

        selectedFiles.forEach((file, index) => {
            const fileItem = document.createElement("li");
            fileItem.className = "file-item";
            
            const infoDiv = document.createElement("div");
            infoDiv.className = "file-item-info";
            
            // Choose file icon based on type
            const ext = file.name.split('.').pop().toLowerCase();
            const iconName = ext === 'pdf' ? "file-text" : "file-code";
            
            infoDiv.innerHTML = `
                <i data-lucide="${iconName}"></i>
                <span class="file-name-truncated" title="${file.name}">${file.name}</span>
            `;
            
            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "file-remove-btn";
            removeBtn.innerHTML = `<i data-lucide="x"></i>`;
            removeBtn.addEventListener("click", () => removeFile(index));
            
            fileItem.appendChild(infoDiv);
            fileItem.appendChild(removeBtn);
            fileList.appendChild(fileItem);
        });

        // Re-compile dynamically loaded lucide icons
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
        stateEmpty.style.display = "none";
        stateLoading.style.display = "none";
        stateError.style.display = "none";
        stateActive.style.display = "none";

        switch (state) {
            case "empty":
                stateEmpty.style.display = "flex";
                break;
            case "loading":
                stateLoading.style.display = "flex";
                break;
            case "error":
                stateError.style.display = "flex";
                break;
            case "active":
                stateActive.style.display = "flex";
                break;
        }
    }

    // -------------------------------------------------------------
    // Form Submission & API Fetching
    // -------------------------------------------------------------
    matchForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        // 1. Validation
        if (selectedFiles.length === 0) {
            alert("Please upload at least one candidate resume (PDF or DOCX).");
            return;
        }

        const jdText = jobDescInput.value.trim();
        if (!jdText) {
            alert("Please paste a job description or keyword criteria.");
            return;
        }

        // 2. Prepare Form Data payload
        const formData = new FormData();
        formData.append("job_description", jdText);
        selectedFiles.forEach(file => {
            formData.append("files", file);
        });

        // 3. Switch to loading UI state
        switchState("loading");
        submitBtn.disabled = true;
        if (selectedFiles.length <= 1) {
            submitBtn.querySelector(".btn-text").textContent = "Analyzing...";
        } else {
            submitBtn.querySelector(".btn-text").textContent = "Analyzing & Ranking...";
        }

        try {
            const response = await fetch(API_URL, {
                method: "POST",
                body: formData
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || "Server failed to process resumes.");
            }

            const data = await response.json();
            renderResults(data);
            switchState("active");

        } catch (error) {
            console.error("API error:", error);
            errorMessage.textContent = error.message || "Failed to establish server connection. Ensure uvicorn backend is running on port 8000.";
            switchState("error");
        } finally {
            submitBtn.disabled = false;
            updateUIForFileCount();
        }
    });

    // Trigger retry
    retryBtn.addEventListener("click", () => {
        submitBtn.click();
    });

    // -------------------------------------------------------------
    // Rendering Results List
    // -------------------------------------------------------------
    function renderResults(data) {
        // Reset contents
        resultsLeaderboard.innerHTML = "";
        jdTextPreview.style.display = "none";
        jdToggleBtn.classList.remove("open");
        jdToggleBtn.querySelector("span").textContent = "Show generated details";

        // 1. Handle Job Description used banner (if expanded by Gemini)
        if (data.is_job_description_expanded) {
            jdBanner.style.display = "flex";
            jdTextPreview.textContent = data.job_description_used;
        } else {
            jdBanner.style.display = "none";
        }

        // 2. Process results leaderboard cards
        const results = data.results || [];
        
        results.forEach((candidate, index) => {
            const card = document.createElement("div");
            card.className = "candidate-card";
            
            // Check status
            if (candidate.status === "error") {
                card.innerHTML = `
                    <div class="card-header-main" style="border-left: 3px solid var(--danger);">
                        <div class="candidate-meta">
                            <span class="rank-badge">${index + 1}</span>
                            <span class="candidate-title" style="color: var(--danger); font-weight: 500;">
                                ${candidate.filename} (Parsing Error)
                            </span>
                        </div>
                        <div class="score-badge-container">
                            <span class="score-badge" style="color: var(--danger); background-color: #fef2f2; border-color: #fca5a5;">
                                Failed
                            </span>
                        </div>
                    </div>
                `;
                resultsLeaderboard.appendChild(card);
                return;
            }

            // Normal successful layout
            const score = candidate.match_score;
            let matchClass = "low-match";
            if (score >= 75) {
                matchClass = "high-match";
            } else if (score >= 50) {
                matchClass = "med-match";
            }

            const analysis = candidate.analysis || {};
            const strengths = analysis.strengths || [];
            const gaps = analysis.gaps || [];
            const recommendations = analysis.recommendations || [];

            // Compile card UI contents
            card.innerHTML = `
                <div class="card-header-main">
                    <div class="candidate-meta">
                        <span class="rank-badge">${index + 1}</span>
                        <span class="candidate-title" title="${candidate.filename}">${candidate.filename}</span>
                    </div>
                    <div class="score-badge-container">
                        <span class="score-badge ${matchClass}">${score}% Fit</span>
                        <i data-lucide="chevron-down" class="card-toggle-icon"></i>
                    </div>
                </div>
                
                <div class="card-details">
                    <!-- 1. AI Professional Summary -->
                    <p class="candidate-summary">
                        ${analysis.summary || "No candidate summary generated."}
                    </p>
                    
                    <!-- 2. Strengths and Gaps grid -->
                    <div class="analysis-grid">
                        <div class="analysis-col">
                            <div class="analysis-col-title strengths-title">
                                <i data-lucide="check-circle2"></i>
                                <span>Key Strengths</span>
                            </div>
                            <ul class="analysis-list strengths-list">
                                ${strengths.map(s => `<li>${s}</li>`).join("") || "<li>No core strengths extracted.</li>"}
                            </ul>
                        </div>
                        <div class="analysis-col">
                            <div class="analysis-col-title gaps-title">
                                <i data-lucide="alert-circle"></i>
                                <span>Critical Gaps</span>
                            </div>
                            <ul class="analysis-list gaps-list">
                                ${gaps.map(g => `<li>${g}</li>`).join("") || "<li>No gaps identified.</li>"}
                            </ul>
                        </div>
                    </div>
                    
                    <!-- 3. Actionable Recommendations -->
                    <div class="recommendations-section">
                        <h4>Optimization Suggestions</h4>
                        <ul class="rec-list">
                            ${recommendations.map(r => `<li>${r}</li>`).join("") || "<li>Resume aligns closely with JD. No recommendations.</li>"}
                        </ul>
                    </div>
                    
                    <!-- 4. Collapsible Raw parsed text (Optional Inspector) -->
                    <div class="card-actions">
                        <button type="button" class="toggle-raw-btn">
                            <i data-lucide="terminal"></i>
                            <span>View Raw Parsed Text</span>
                        </button>
                    </div>
                    <pre class="raw-text-wrapper">${escapeHTML(candidate.raw_text)}</pre>
                </div>
            `;

            // Toggle Expand Card Details
            const header = card.querySelector(".card-header-main");
            header.addEventListener("click", () => {
                const isOpen = card.classList.contains("open");
                // Close all cards first for accordion clean experience
                document.querySelectorAll(".candidate-card").forEach(c => c.classList.remove("open"));
                if (!isOpen) {
                    card.classList.add("open");
                }
            });

            // Toggle Raw Extracted Text panel
            const toggleRawBtn = card.querySelector(".toggle-raw-btn");
            const rawTextWrapper = card.querySelector(".raw-text-wrapper");
            toggleRawBtn.addEventListener("click", (e) => {
                e.stopPropagation(); // Avoid triggering card accordion collapse
                const isRawOpen = rawTextWrapper.style.display === "block";
                rawTextWrapper.style.display = isRawOpen ? "none" : "block";
                toggleRawBtn.querySelector("span").textContent = isRawOpen ? "View Raw Parsed Text" : "Hide Raw Parsed Text";
            });

            resultsLeaderboard.appendChild(card);
        });

        // Initialize icons inside results cards
        lucide.createIcons();
    }

    // Toggle job description expansion banner
    jdToggleBtn.addEventListener("click", () => {
        const isClosed = jdTextPreview.style.display === "none";
        jdTextPreview.style.display = isClosed ? "block" : "none";
        jdToggleBtn.classList.toggle("open", isClosed);
        jdToggleBtn.querySelector("span").textContent = isClosed ? "Hide generated details" : "Show generated details";
    });

    // Helper to prevent HTML injection attacks in raw text inspector
    function escapeHTML(text) {
        if (!text) return "";
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
});
