window.latestRequirements = "";

const generateRequirementsButton = document.getElementById("analyzeBtn");
const generateProjectButton = document.getElementById("generateProjectBtn");
const requirementsOutput = document.getElementById("requirementsOutput");
const editRequirementsButton = document.getElementById("editBtn");
const saveRequirementsButton = document.getElementById("saveBtn");
const cancelRequirementsButton = document.getElementById("cancelBtn");
const generationStatus = document.getElementById("generationStatus");
const generationLogs = document.getElementById("generationLogs");
const deployButton = document.getElementById("deployBtn");
const deploymentStatus = document.getElementById("deploymentStatus");
let savedRequirements = "";
let liveGenerationText = "";
let liveGenerationGroup = "";
let liveGenerationFrame = 0;

function renderLiveGeneratedCode() {
    liveGenerationFrame = 0;
    const codeBlock = document.querySelector("#codeViewer code");
    if (!codeBlock) {
        return;
    }

    const headings = [
        ...liveGenerationText.matchAll(
            /^#{2,3}\s+(.+?)\s*:?\r?\n\s*```[^\r\n]*\r?\n/gm
        )
    ];
    const latestHeading = headings[headings.length - 1];
    let content = liveGenerationText;
    let path = "Live generation output";
    if (latestHeading) {
        path = latestHeading[1].trim().replace(/^[`'"]|[`'"]$/g, "");
        if (path.startsWith("project/")) {
            path = path.slice("project/".length);
        }
        content = liveGenerationText.slice(
            latestHeading.index + latestHeading[0].length
        );
    }
    content = content.replace(/\r?\n```[ \t]*\r?\n?$/, "");

    document.getElementById("codeFileName").textContent = path;
    document.getElementById("editorTabName").textContent =
        path.split("/").pop() || "Generating code";
    document.getElementById("languageBadge").textContent = "GENERATING";
    document.getElementById("lineCount").textContent =
        `${content.split("\n").length} lines`;
    document.getElementById("downloadCodeButton").disabled = true;
    codeBlock.className = "language-plaintext";
    codeBlock.textContent = content || "Waiting for generated code...";
    document.getElementById("codeLineNumbers").textContent =
        Array.from(
            { length: Math.max(content.split("\n").length, 1) },
            (_, index) => index + 1
        ).join("\n");
    const viewer = document.getElementById("codeViewer");
    viewer.scrollTop = viewer.scrollHeight;
    document.getElementById("codeLineNumbers").scrollTop = viewer.scrollTop;
}

function scheduleLiveCodeRender() {
    if (!liveGenerationFrame) {
        liveGenerationFrame = requestAnimationFrame(renderLiveGeneratedCode);
    }
}

function appendGenerationLog(message, level = "info") {
    const entry = document.createElement("li");
    entry.textContent = message;
    entry.className = `log-${level}`;
    generationLogs.appendChild(entry);
    generationStatus.textContent = message;
}

function renderDiagram(elementId, source, emptyMessage) {
    const container = document.getElementById(elementId);
    if (!source) {
        container.textContent = emptyMessage;
        return;
    }

    const diagram = document.createElement("div");
    diagram.className = "mermaid";
    diagram.textContent = source;
    container.replaceChildren(diagram);
    if (window.mermaid) {
        window.mermaid.run({ nodes: [diagram] }).catch(error => {
            console.warn("Diagram rendering failed:", error);
        });
    }
}

function renderTable(containerId, headers, rows, emptyMessage) {
    const container = typeof containerId === "string"
        ? document.getElementById(containerId)
        : containerId;
    container.replaceChildren();
    if (!rows.length) {
        container.textContent = emptyMessage;
        return;
    }

    const table = document.createElement("table");
    const head = document.createElement("thead");
    const headerRow = document.createElement("tr");
    headers.forEach(header => {
        const cell = document.createElement("th");
        cell.textContent = header;
        headerRow.appendChild(cell);
    });
    head.appendChild(headerRow);
    table.appendChild(head);

    const body = document.createElement("tbody");
    rows.forEach(row => {
        const tableRow = document.createElement("tr");
        headers.forEach(header => {
            const cell = document.createElement("td");
            const value = row[header];
            cell.textContent = Array.isArray(value)
                ? value.join(", ")
                : value && typeof value === "object"
                    ? Object.entries(value).map(([key, item]) => `${key}: ${item}`).join("; ")
                    : value == null
                        ? ""
                        : String(value);
            tableRow.appendChild(cell);
        });
        body.appendChild(tableRow);
    });
    table.appendChild(body);
    container.appendChild(table);
}

function displayGenerationData(data) {
    if (data.type === "requirements") {
        window.latestRequirements = data.requirements;
        requirementsOutput.value = data.requirements;
        return;
    }

    if (data.type === "architecture") {
        window.latestArchitecture = data.architecture;
        document.getElementById("architectureOutput").textContent =
            "Architecture generated successfully.";
        renderDiagram(
            "architectureDiagram",
            data.architecture.architecture_diagram,
            "No architecture diagram was generated."
        );
        return;
    }

    if (data.type === "database") {
        window.latestDatabase = data.database;
        document.getElementById("databaseOutput").textContent =
            "Database design generated successfully.";
        const databaseTables = document.getElementById("databaseTables");
        databaseTables.replaceChildren();
        (data.database.tables || []).forEach(tableData => {
            const tableContainer = document.createElement("div");
            tableContainer.className = "database-table";
            const heading = document.createElement("h4");
            heading.textContent = tableData.table_name || "Table";
            tableContainer.appendChild(heading);
            databaseTables.appendChild(tableContainer);
            renderTable(
                tableContainer,
                ["Column", "Type", "Primary key", "Foreign key"],
                (tableData.columns || []).map(column => ({
                    Column: column.name || "",
                    Type: column.type || "",
                    "Primary key": column.primary_key ? "Yes" : "No",
                    "Foreign key": column.foreign_key || ""
                })),
                "No columns generated."
            );
            tableContainer.prepend(heading);
        });
        renderDiagram(
            "databaseERD",
            data.database.erd,
            "No ER diagram was generated."
        );
    }
}

async function consumeGenerationStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffered = "";

    while (true) {
        const { value, done } = await reader.read();
        buffered += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffered.split("\n");
        buffered = lines.pop();

        for (const line of lines) {
            if (!line.trim()) {
                continue;
            }
            handleGenerationEvent(JSON.parse(line));
        }

        if (done) {
            break;
        }
    }

    if (buffered.trim()) {
        handleGenerationEvent(JSON.parse(buffered));
    }
}

function handleGenerationEvent(event) {
    if (event.type === "log") {
        const level = /failed|validation failed/i.test(event.message)
            ? "error"
            : "info";
        appendGenerationLog(event.message, level);
        return;
    }

    if (event.type === "code_start") {
        liveGenerationGroup =
            `${(event.files || []).join(",")}:${event.attempt || 1}`;
        liveGenerationText = "";
        document.getElementById("projectExplorerSection").hidden = false;
        document.getElementById("generationStatus").textContent =
            `Generating code for ${(event.files || []).join(", ")}...`;
        if (!generatedProjectFiles.length) {
            document.getElementById("projectTree").textContent =
                "Receiving generated files...";
        }
        scheduleLiveCodeRender();
        return;
    }

    if (event.type === "code_chunk") {
        const group = `${(event.files || []).join(",")}:${event.attempt || 1}`;
        if (group !== liveGenerationGroup) {
            liveGenerationGroup = group;
            liveGenerationText = "";
        }
        liveGenerationText += event.content || "";
        scheduleLiveCodeRender();
        return;
    }

    if (event.type === "code_files") {
        if (liveGenerationFrame) {
            cancelAnimationFrame(liveGenerationFrame);
            renderLiveGeneratedCode();
        }
        const updatedFiles = new Map(
            generatedProjectFiles.map(file => [file.path, file])
        );
        (event.files || []).forEach(file => updatedFiles.set(file.path, file));
        loadProjectFiles([...updatedFiles.values()]);
        return;
    }

    if (["requirements", "architecture", "database"].includes(event.type)) {
        displayGenerationData(event);
        return;
    }

    if (event.type === "complete" && event.success) {
        const project = event.project;
        window.currentProjectId = project.project_id;
        sessionStorage.setItem("currentProjectId", project.project_id);
        document.getElementById("projectOutput").textContent =
            `${project.message ? `${project.message}\n` : ""}` +
            `Project path: ${project.project_path}\n` +
            `Backend generated: ${project.backend_generated ? "Yes" : "No"}\n` +
            `Frontend generated: ${project.frontend_generated ? "Yes" : "No"}`;
        document.getElementById("generatedProjectSection").hidden = false;
        document.getElementById("projectExplorerSection").hidden = false;
        document.getElementById("documentationSection").hidden = false;
        document.getElementById("downloadBtn").disabled = false;
        deployButton.disabled = false;
        if (project.partial) {
            generationStatus.textContent = project.message;
        }
        loadProjectFiles(project.files);
        loadProjectHistory();
        refreshSelectedProjectDetails().catch(error => {
            console.error("Could not load generated project history:", error);
            generationStatus.textContent =
                `Project generated, but its saved details could not be loaded: ${error.message}`;
        });
        return;
    }

    if (event.type === "failure") {
        generationStatus.textContent = "Project generation failed.";
        appendGenerationLog(event.message, "error");
    }
}

generateRequirementsButton.addEventListener("click", async () => {
    const prompt = document.getElementById("prompt").value.trim();
    if (!prompt) {
        alert("Enter Project Description");
        return;
    }

    deployButton.disabled = true;
    deploymentStatus.textContent = "";
    generateRequirementsButton.disabled = true;
    generateProjectButton.disabled = true;
    editRequirementsButton.disabled = true;
    requirementsOutput.value = "";
    generationLogs.replaceChildren();
    appendGenerationLog("Requirements generation started...");
    document.getElementById("generatedProjectSection").hidden = true;
    document.getElementById("projectExplorerSection").hidden = true;
    document.getElementById("documentationSection").hidden = true;
    document.getElementById("downloadBtn").disabled = true;
    deployButton.disabled = true;
    deploymentStatus.textContent = "";

    try {
        const response = await fetch("/api/requirements", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.message || "Requirements generation failed.");
        }

        savedRequirements = data.requirements;
        window.latestRequirements = savedRequirements;
        requirementsOutput.value = savedRequirements;
        editRequirementsButton.disabled = false;
        generateProjectButton.disabled = false;
        appendGenerationLog("Requirements generated successfully.");
    } catch (error) {
        console.error("Requirements generation error:", error);
        appendGenerationLog(`Requirements generation failed: ${error.message}`, "error");
    } finally {
        generateRequirementsButton.disabled = false;
    }
});

editRequirementsButton.addEventListener("click", () => {
    requirementsOutput.readOnly = false;
    requirementsOutput.focus();
    generateRequirementsButton.disabled = true;
    editRequirementsButton.style.display = "none";
    saveRequirementsButton.style.display = "inline-block";
    cancelRequirementsButton.style.display = "inline-block";
    generateProjectButton.disabled = true;
});

saveRequirementsButton.addEventListener("click", () => {
    savedRequirements = requirementsOutput.value.trim();
    if (!savedRequirements) {
        appendGenerationLog("Requirements cannot be empty.", "error");
        savedRequirements = window.latestRequirements;
        return;
    }
    window.latestRequirements = savedRequirements;
    requirementsOutput.value = savedRequirements;
    requirementsOutput.readOnly = true;
    generateRequirementsButton.disabled = false;
    editRequirementsButton.style.display = "inline-block";
    saveRequirementsButton.style.display = "none";
    cancelRequirementsButton.style.display = "none";
    generateProjectButton.disabled = !savedRequirements;
    appendGenerationLog("Edited requirements saved.");
});

cancelRequirementsButton.addEventListener("click", () => {
    requirementsOutput.value = savedRequirements;
    requirementsOutput.readOnly = true;
    generateRequirementsButton.disabled = false;
    editRequirementsButton.style.display = "inline-block";
    saveRequirementsButton.style.display = "none";
    cancelRequirementsButton.style.display = "none";
    generateProjectButton.disabled = !savedRequirements;
});

generateProjectButton.addEventListener("click", async () => {
    const requirements = window.latestRequirements.trim();
    if (!requirements) {
        appendGenerationLog("Generate requirements before starting the project.", "error");
        return;
    }

    generateProjectButton.disabled = true;
    generateRequirementsButton.disabled = true;
    generationStatus.textContent =
        "Starting project generation. Code generation has a 15-minute limit.";
    document.getElementById("generatedProjectSection").hidden = true;
    document.getElementById("projectExplorerSection").hidden = false;
    document.getElementById("documentationSection").hidden = true;
    document.getElementById("projectExplorerSection").scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
    document.getElementById("downloadBtn").disabled = true;
    deployButton.disabled = true;
    deploymentStatus.textContent = "";
    liveGenerationText = "";
    liveGenerationGroup = "";
    window.currentProjectId = "";
    sessionStorage.removeItem("currentProjectId");
    await loadProjectFiles([]);
    if (!generatedProjectFiles.length) {
        document.getElementById("projectTree").textContent =
            "Waiting for generated files...";
        showEmptyEditor("Generated code will appear here as it is produced.");
    }

    try {
        const response = await fetch("/api/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                prompt: document.getElementById("prompt").value.trim(),
                requirements
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || "Project generation failed.");
        }

        const projectId = response.headers.get("X-Project-Id");
        if (!projectId) {
            throw new Error("Project generation did not return a project ID.");
        }
        window.currentProjectId = projectId;
        sessionStorage.setItem("currentProjectId", projectId);
        await consumeGenerationStream(response);
    } catch (error) {
        console.error("Project generation error:", error);
        appendGenerationLog(error.message, "error");
    } finally {
        generateProjectButton.disabled = !window.latestRequirements;
        generateRequirementsButton.disabled = false;
    }
});

// ==================================================
// AUTOMATED CLOUD DEPLOYMENT (NEON DB + RENDER)
// ==================================================

const deployModalBackdrop = document.getElementById("deployModalBackdrop");
const closeDeployModalBtn = document.getElementById("closeDeployModalBtn");
const cancelDeployBtn = document.getElementById("cancelDeployBtn");
const startDeployBtn = document.getElementById("startDeployBtn");
const deployConfigForm = document.getElementById("deployConfigForm");
const deployProgressView = document.getElementById("deployProgressView");
const deployTerminal = document.getElementById("deployTerminal");
const deploySuccessCard = document.getElementById("deploySuccessCard");
const deployErrorCard = document.getElementById("deployErrorCard");
const deployedLiveLink = document.getElementById("deployedLiveLink");
const deployNeonSummary = document.getElementById("deployNeonSummary");
const deployGithubLink = document.getElementById("deployGithubLink");
const deployRenderLink = document.getElementById("deployRenderLink");
const finishDeployBtn = document.getElementById("finishDeployBtn");
const backToConfigBtn = document.getElementById("backToConfigBtn");

const neonStatusBadge = document.getElementById("neonStatusBadge");
const githubStatusBadge = document.getElementById("githubStatusBadge");
const renderStatusBadge = document.getElementById("renderStatusBadge");

const neonApiKeyInput = document.getElementById("neonApiKey");
const neonDatabaseUrlInput = document.getElementById("neonDatabaseUrl");
const githubTokenInput = document.getElementById("githubToken");
const githubRepoNameInput = document.getElementById("githubRepoName");
const githubIsPrivateCheck = document.getElementById("githubIsPrivate");
const renderApiKeyInput = document.getElementById("renderApiKey");
const renderServiceNameInput = document.getElementById("renderServiceName");
const saveToEnvCheck = document.getElementById("saveToEnvCheck");
const simulateDeployCheck = document.getElementById("simulateDeployCheck");

function openDeployModal() {
    if (!deployModalBackdrop) return;
    deployModalBackdrop.classList.add("active");
    deployModalBackdrop.setAttribute("aria-hidden", "false");
    deployConfigForm.style.display = "block";
    deployProgressView.style.display = "none";
    deploySuccessCard.style.display = "none";
    deployErrorCard.style.display = "none";
    deployTerminal.replaceChildren();

    // Reset step styles
    ["step-neon", "step-github", "step-render", "step-live"].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.classList.remove("active", "completed");
        }
    });

    fetchDeployConfig();
}

function closeDeployModal() {
    if (!deployModalBackdrop) return;
    deployModalBackdrop.classList.remove("active");
    deployModalBackdrop.setAttribute("aria-hidden", "true");
}

async function fetchDeployConfig() {
    try {
        const res = await fetch("/api/deploy/config");
        if (!res.ok) {
            throw new Error("Deployment settings could not be loaded.");
        }
        const data = await res.json();
        const conf = data.configured || {};

        if (conf.has_neon_api_key || conf.has_neon_database_url) {
            neonStatusBadge.textContent = "Configured on server";
            neonStatusBadge.className = "deploy-status-badge configured";
        } else {
            neonStatusBadge.textContent = "Not Set";
            neonStatusBadge.className = "deploy-status-badge not-configured";
        }

        if (conf.has_github_token) {
            githubStatusBadge.textContent = "Configured on server";
            githubStatusBadge.className = "deploy-status-badge configured";
        } else {
            githubStatusBadge.textContent = "Not Set";
            githubStatusBadge.className = "deploy-status-badge not-configured";
        }

        if (conf.has_render_api_key) {
            renderStatusBadge.textContent = "Configured on server";
            renderStatusBadge.className = "deploy-status-badge configured";
        } else {
            renderStatusBadge.textContent = "Not Set";
            renderStatusBadge.className = "deploy-status-badge not-configured";
        }
    } catch (e) {
        console.error("Could not fetch deploy configuration:", e);
        [neonStatusBadge, githubStatusBadge, renderStatusBadge].forEach(badge => {
            badge.textContent = "Configuration unavailable";
            badge.className = "deploy-status-badge not-configured";
        });
    }
}

function appendDeployTerminalLog(message, type = "info") {
    if (!deployTerminal) return;
    const line = document.createElement("div");
    line.className = `deploy-terminal-line ${type}`;
    const timestamp = new Date().toLocaleTimeString([], { hour12: false });
    line.textContent = `[${timestamp}] ${message}`;
    deployTerminal.appendChild(line);
    deployTerminal.scrollTop = deployTerminal.scrollHeight;
}

function setStepState(stepId, state) {
    const el = document.getElementById(`step-${stepId}`);
    if (!el) return;
    if (state === "active") {
        el.classList.add("active");
        el.classList.remove("completed");
    } else if (state === "completed") {
        el.classList.remove("active");
        el.classList.add("completed");
    }
}

deployButton.addEventListener("click", () => {
    const projectId = window.currentProjectId || sessionStorage.getItem("currentProjectId");
    if (!projectId) {
        deploymentStatus.textContent = "Generate a project before deploying.";
        alert("Please generate a project before deploying.");
        return;
    }
    openDeployModal();
});

if (closeDeployModalBtn) {
    closeDeployModalBtn.addEventListener("click", closeDeployModal);
}
if (cancelDeployBtn) {
    cancelDeployBtn.addEventListener("click", closeDeployModal);
}
if (finishDeployBtn) {
    finishDeployBtn.addEventListener("click", closeDeployModal);
}

if (backToConfigBtn) {
    backToConfigBtn.addEventListener("click", () => {
        deployConfigForm.style.display = "block";
        deployProgressView.style.display = "none";
        backToConfigBtn.style.display = "none";
        startDeployBtn.disabled = false;
    });
}

if (startDeployBtn) {
    startDeployBtn.addEventListener("click", async () => {
        const projectId = window.currentProjectId || sessionStorage.getItem("currentProjectId");
        if (!projectId) {
            alert("Please generate a project before deploying.");
            return;
        }

        // Switch to progress view
        deployConfigForm.style.display = "none";
        deployProgressView.style.display = "block";
        deploySuccessCard.style.display = "none";
        deployErrorCard.style.display = "none";
        backToConfigBtn.style.display = "none";
        finishDeployBtn.style.display = "none";
        deploymentStatus.textContent = "";
        deployTerminal.replaceChildren();

        const payload = {
            project_id: projectId,
            neon_api_key: neonApiKeyInput.value.trim(),
            neon_database_url: neonDatabaseUrlInput.value.trim(),
            github_token: githubTokenInput.value.trim(),
            repo_name: githubRepoNameInput.value.trim(),
            is_private: githubIsPrivateCheck.checked,
            render_api_key: renderApiKeyInput.value.trim(),
            service_name: renderServiceNameInput.value.trim(),
            save_to_env: saveToEnvCheck.checked,
            simulate: simulateDeployCheck.checked,
        };

        setStepState("neon", "active");
        appendDeployTerminalLog(`Initiating deployment pipeline for ${projectId}...`, "info");
        startDeployBtn.disabled = true;
        let deploymentFinished = false;

        try {
            const response = await fetch("/api/deploy", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok && !response.headers.get("content-type")?.includes("ndjson")) {
                const errData = await response.json();
                throw new Error(errData.message || "Failed to start deployment.");
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed) continue;
                    try {
                        const event = JSON.parse(trimmed);
                        handleDeployEvent(event);
                        if (event.type === "complete" || event.type === "failure") {
                            deploymentFinished = true;
                        }
                    } catch (jsonErr) {
                        console.warn("JSON parse error in deploy stream:", jsonErr, trimmed);
                    }
                }
            }

            if (buffer.trim()) {
                try {
                    const event = JSON.parse(buffer.trim());
                    handleDeployEvent(event);
                    if (event.type === "complete" || event.type === "failure") {
                        deploymentFinished = true;
                    }
                } catch (e) {
                    console.warn("Failed to parse remaining deploy buffer:", e);
                }
            }
            if (!deploymentFinished) {
                throw new Error("Deployment stream ended before reporting a final result.");
            }
        } catch (error) {
            appendDeployTerminalLog(`Deployment error: ${error.message}`, "error");
            deployErrorCard.textContent = `Deployment Error: ${error.message}`;
            deployErrorCard.style.display = "block";
            backToConfigBtn.style.display = "inline-block";
            deploymentStatus.textContent = `Deployment failed: ${error.message}`;
        } finally {
            startDeployBtn.disabled = false;
        }
    });
}

function handleDeployEvent(event) {
    if (event.type === "log") {
        const isErr = /error|failed/i.test(event.message);
        appendDeployTerminalLog(event.message, isErr ? "error" : "info");
        return;
    }

    if (event.type === "step") {
        const step = event.step;
        if (event.status === "running") {
            setStepState(step, "active");
            appendDeployTerminalLog(`[Step] ${event.message}`, "info");
        } else if (event.status === "completed") {
            setStepState(step, "completed");
            appendDeployTerminalLog(`[Step Complete] ${event.message}`, "success");
        } else if (event.status === "failed") {
            appendDeployTerminalLog(`[Step Failed] ${event.message}`, "error");
        }
        return;
    }

    if (event.type === "complete") {
        const simulated = event.simulated === true;
        setStepState("neon", "completed");
        setStepState("github", "completed");
        setStepState("render", "completed");
        if (!simulated) {
            setStepState("live", "completed");
        }

        appendDeployTerminalLog(
            simulated ? "Demo simulation completed. No cloud resources were created." :
                "Render confirmed that the deployment is live.",
            "success"
        );

        // Display success card
        deploySuccessCard.style.display = "block";
        finishDeployBtn.style.display = "inline-block";
        document.getElementById("deploySuccessBadge").textContent = simulated
            ? "ℹ️ Demo Complete"
            : "✅ Deployed Successfully";
        document.getElementById("deploySuccessTitle").textContent = simulated
            ? "This was a deployment simulation"
            : "Your Application is Live on Render!";
        document.getElementById("deploySuccessDescription").textContent = simulated
            ? "No database, GitHub repository, or Render service was created."
            : "The database schema was applied to Neon, code pushed to GitHub, and Render confirmed the web service is live.";

        // Setup the live openable link
        if (deployedLiveLink) {
            deployedLiveLink.hidden = simulated || !event.url;
            deployedLiveLink.href = event.url;
            deployedLiveLink.textContent = `🌐 Open Live Application: ${event.url} ↗`;
        }

        // Setup Neon summary
        if (deployNeonSummary && event.neon) {
            const tables = event.neon.tables || [];
            deployNeonSummary.textContent = simulated
                ? "Demo only; no database created"
                : tables.length
                ? `Connected (${tables.length} tables created: ${tables.slice(0, 3).join(", ")}${tables.length > 3 ? "..." : ""})`
                : "Schema deployed successfully";
        }

        // Setup GitHub link
        if (deployGithubLink) {
            deployGithubLink.closest(".deploy-link-box").hidden =
                simulated || !event.github?.repo_url;
        }
        if (!simulated && deployGithubLink && event.github?.repo_url) {
            deployGithubLink.href = event.github.repo_url;
            deployGithubLink.textContent = "View on GitHub ↗";
        }

        // Setup Render link
        if (deployRenderLink) {
            deployRenderLink.closest(".deploy-link-box").hidden = simulated;
        }
        if (!simulated && deployRenderLink && (event.render?.dashboard_url || event.url)) {
            deployRenderLink.href = event.render.dashboard_url || event.url;
            deployRenderLink.textContent = "View on Render ↗";
        }

        if (deploymentStatus) {
            if (simulated) {
                deploymentStatus.textContent =
                    "Demo simulation completed. No cloud resources were created.";
            } else if (event.url) {
                const banner = document.createElement("div");
                banner.className = "deployed-live-banner";
                const details = document.createElement("div");
                const heading = document.createElement("strong");
                heading.textContent = "🎉 Project Live on Render!";
                const description = document.createElement("div");
                description.style.cssText = "font-size:0.85rem;color:#166534;margin-top:2px;";
                description.textContent = "Neon database provisioned and Render confirmed the web service is live.";
                details.append(heading, description);
                const link = document.createElement("a");
                link.href = event.url;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.className = "live-link-pill";
                link.textContent = `🌐 Open Live App (${event.url}) ↗`;
                banner.append(details, link);
                deploymentStatus.replaceChildren(banner);
            }
        }
        loadProjectHistory();
        refreshSelectedProjectDetails().catch(error => {
            console.error("Could not refresh deployed project details:", error);
        });
        return;
    }

    if (event.type === "failure") {
        appendDeployTerminalLog(`Deployment Failed: ${event.message}`, "error");
        deployErrorCard.textContent = `Deployment Failed: ${event.message}`;
        deployErrorCard.style.display = "block";
        backToConfigBtn.style.display = "inline-block";
        deploymentStatus.textContent = `Deployment failed: ${event.message}`;
        loadProjectHistory();
        refreshSelectedProjectDetails().catch(error => {
            console.error("Could not refresh failed deployment details:", error);
        });
    }
}

// ============================================================
// PROJECT HISTORY
// ============================================================

const historyList = document.getElementById("projectHistoryList");
const historyDetails = document.getElementById("projectHistoryDetails");
const refreshHistoryBtn = document.getElementById("refreshHistoryBtn");
const historyToggleBtn = document.getElementById("historyToggleBtn");
const projectHistorySection = document.getElementById("projectHistorySection");

function historyDate(value) {
    if (!value) return "Unknown date";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function safeHistoryUrl(value) {
    try {
        const url = new URL(value);
        return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch {
        return "";
    }
}

function setHistoryPanelOpen(isOpen) {
    if (!projectHistorySection || !historyToggleBtn) return;
    projectHistorySection.hidden = !isOpen;
    historyToggleBtn.setAttribute("aria-expanded", String(isOpen));
    if (isOpen) loadProjectHistory();
}

function createDeploymentSummary(deployment) {
    const simulated = deployment.status === "simulated";
    const summary = deployment.summary || {};
    const card = document.createElement("div");
    card.className = "deploy-success-card history-deployment-summary";

    const badge = document.createElement("div");
    badge.className = "deploy-success-badge";
    badge.textContent = simulated ? "Demo Complete" : "Deployed Successfully";
    card.appendChild(badge);

    const title = document.createElement("h4");
    title.textContent = summary.title || (simulated
        ? "This was a deployment simulation"
        : "Your Application is Live on Render!");
    card.appendChild(title);

    const description = document.createElement("p");
    description.textContent = summary.description || (simulated
        ? "No database, GitHub repository, or Render service was created."
        : "The database schema was applied to Neon, code pushed to GitHub, and Render confirmed the web service is live.");
    card.appendChild(description);

    if (!simulated && safeHistoryUrl(deployment.url)) {
        const liveLink = document.createElement("a");
        liveLink.className = "btn-open-deployed-app";
        liveLink.href = deployment.url;
        liveLink.target = "_blank";
        liveLink.rel = "noopener noreferrer";
        liveLink.textContent = `Open Live Application: ${deployment.url} ↗`;
        card.appendChild(liveLink);
    }

    const linksGrid = document.createElement("div");
    linksGrid.className = "deploy-links-grid";
    const tables = deployment.neon?.tables || [];
    const neonText = simulated ? "Demo only; no database created" : tables.length
        ? `Connected (${tables.length} tables created: ${tables.slice(0, 3).join(", ")}${tables.length > 3 ? "..." : ""})`
        : "Schema deployed successfully";
    const boxes = [
        ["Neon Database", neonText],
        ["GitHub Repository", deployment.github?.repo_url],
        ["Render Dashboard", deployment.render?.dashboard_url || deployment.url]
    ];
    boxes.forEach(([label, value]) => {
        if (!value || simulated && label !== "Neon Database") return;
        const box = document.createElement("div");
        box.className = "deploy-link-box";
        const boxTitle = document.createElement("strong");
        boxTitle.textContent = label;
        box.appendChild(boxTitle);
        if (label === "Neon Database") {
            box.appendChild(document.createTextNode(value));
        } else {
            const safeUrl = safeHistoryUrl(value);
            if (!safeUrl) return;
            const link = document.createElement("a");
            link.href = safeUrl;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = label === "GitHub Repository" ? "View on GitHub ↗" : "View on Render ↗";
            box.appendChild(link);
        }
        linksGrid.appendChild(box);
    });
    if (linksGrid.children.length) card.appendChild(linksGrid);
    return card;
}

function renderHistoryDetails(project) {
    if (!historyDetails) return;
    historyDetails.replaceChildren();
    historyDetails.hidden = false;

    const heading = document.createElement("h3");
    heading.textContent = project.title || project.project_id;
    historyDetails.appendChild(heading);
    const grid = document.createElement("div");
    grid.className = "history-detail-grid";
    [
        ["Project ID", project.project_id],
        ["Created", historyDate(project.created_at)],
        ["Last updated", historyDate(project.updated_at)],
        ["Status", project.status || "saved"]
    ].forEach(([label, value]) => {
        const item = document.createElement("div");
        item.className = "history-detail-item";
        const strong = document.createElement("strong");
        strong.textContent = label;
        item.append(strong, document.createTextNode(value || "Not available"));
        grid.appendChild(item);
    });
    historyDetails.appendChild(grid);

    const deployment = project.deployment || {};
    if (["deployed", "simulated"].includes(deployment.status)) {
        historyDetails.appendChild(createDeploymentSummary(deployment));
    }
    const deploymentSection = document.createElement("section");
    deploymentSection.className = "history-record-section";
    const deploymentTitle = document.createElement("h4");
    deploymentTitle.textContent = "Deployment";
    const deploymentStatusText = document.createElement("p");
    deploymentStatusText.textContent =
        `Status: ${deployment.status || "not deployed"}` +
        (deployment.message ? ` · ${deployment.message}` : "");
    deploymentSection.append(deploymentTitle, deploymentStatusText);
    const links = document.createElement("div");
    links.className = "history-links";
    [["Live application", deployment.url], ["GitHub repository", deployment.github?.repo_url],
        ["Render dashboard", deployment.render?.dashboard_url]].forEach(([label, url]) => {
        const safeUrl = safeHistoryUrl(url);
        if (!safeUrl) return;
        const link = document.createElement("a");
        link.href = safeUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `${label}: ${safeUrl}`;
        links.appendChild(link);
    });
    if (links.children.length) deploymentSection.appendChild(links);
    if (!["deployed", "simulated"].includes(deployment.status)) {
        historyDetails.appendChild(deploymentSection);
    }
}

async function refreshSelectedProjectDetails() {
    const projectId = window.currentProjectId;
    if (!projectId) return;
    const response = await fetch(`/api/history/${encodeURIComponent(projectId)}`);
    const data = await response.json();
    if (!response.ok || !data.success) {
        throw new Error(data.message || "Unable to refresh project details.");
    }
    if (window.currentProjectId !== projectId) return;
    renderHistoryDetails(data.project);
}

async function openProjectHistory(projectId) {
    const response = await fetch(`/api/history/${encodeURIComponent(projectId)}`);
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.message || "Unable to open project history.");
    const project = data.project;
    window.currentProjectId = project.project_id;
    sessionStorage.setItem("currentProjectId", project.project_id);
    document.getElementById("prompt").value = project.prompt || "";
    window.latestRequirements = project.requirements || "";
    savedRequirements = window.latestRequirements;
    requirementsOutput.value = window.latestRequirements;
    requirementsOutput.readOnly = true;
    editRequirementsButton.disabled = false;
    generateProjectButton.disabled = false;
    if (project.architecture && Object.keys(project.architecture).length) displayGenerationData({type: "architecture", architecture: project.architecture});
    if (project.database && Object.keys(project.database).length) displayGenerationData({type: "database", database: project.database});
    renderHistoryDetails(project);
    document.getElementById("generatedProjectSection").hidden = false;
    document.getElementById("projectExplorerSection").hidden = false;
    document.getElementById("projectOutput").textContent = `${project.title || project.project_id}\nProject ID: ${project.project_id}`;
    deployButton.disabled = false;
    setHistoryPanelOpen(false);
    await loadProjectFiles();
    await loadProjectHistory();
    document.getElementById("generatedProjectSection").scrollIntoView({behavior: "smooth", block: "start"});
}

async function deleteProjectHistory(projectId) {
    if (!confirm("Delete this generated project and all saved history?")) return;
    const response = await fetch(`/api/history/${encodeURIComponent(projectId)}`, {method: "DELETE"});
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.message || "Unable to delete project.");
    if (window.currentProjectId === projectId) {
        window.currentProjectId = "";
        sessionStorage.removeItem("currentProjectId");
        historyDetails.hidden = true;
        document.getElementById("generatedProjectSection").hidden = true;
        document.getElementById("projectExplorerSection").hidden = true;
    }
    await loadProjectHistory();
}

async function loadProjectHistory() {
    if (!historyList) return;
    try {
        const response = await fetch("/api/history");
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || "Unable to load history.");
        historyList.replaceChildren();
        if (!data.projects.length) {
            historyList.innerHTML = '<div class="history-empty">No generated projects yet.</div>';
            return;
        }
        data.projects.forEach(project => {
            const card = document.createElement("article");
            card.className = "history-card";
            if (project.project_id === window.currentProjectId) card.classList.add("selected");
            const text = document.createElement("div");
            const title = document.createElement("div");
            title.className = "history-card-title";
            title.textContent = project.title || project.project_id;
            const meta = document.createElement("div");
            meta.className = "history-card-meta";
            meta.textContent = `${project.project_id} · ${historyDate(project.updated_at)} · ${project.deployment?.status || "not deployed"}`;
            text.append(title, meta);
            if (project.prompt) {
                const prompt = document.createElement("div");
                prompt.className = "history-card-prompt";
                prompt.textContent = project.prompt;
                text.appendChild(prompt);
            }
            const deployment = project.deployment || {};
            const projectLinks = document.createElement("div");
            projectLinks.className = "history-card-links";
            [["Live application", deployment.url],
                ["GitHub repository", deployment.github?.repo_url],
                ["Render dashboard", deployment.render?.dashboard_url]].forEach(([label, url]) => {
                const safeUrl = safeHistoryUrl(url);
                if (!safeUrl) return;
                const link = document.createElement("a");
                link.href = safeUrl;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = label;
                projectLinks.appendChild(link);
            });
            if (projectLinks.children.length) {
                text.appendChild(projectLinks);
            }
            const actions = document.createElement("div");
            actions.className = "history-card-actions";
            const open = document.createElement("button");
            open.className = "history-open-btn";
            open.textContent = "Open";
            open.addEventListener("click", () => openProjectHistory(project.project_id).catch(error => alert(error.message)));
            const remove = document.createElement("button");
            remove.className = "history-delete-btn";
            remove.textContent = "Delete";
            remove.addEventListener("click", () => deleteProjectHistory(project.project_id).catch(error => alert(error.message)));
            actions.append(open, remove);
            card.append(text, actions);
            historyList.appendChild(card);
        });
    } catch (error) {
        historyList.textContent = `Unable to load project history: ${error.message}`;
    }
}

if (refreshHistoryBtn) refreshHistoryBtn.addEventListener("click", loadProjectHistory);
if (historyToggleBtn) {
    historyToggleBtn.addEventListener("click", () => {
        setHistoryPanelOpen(projectHistorySection.hidden);
    });
}
document.addEventListener("click", event => {
    if (!projectHistorySection || projectHistorySection.hidden) return;
    if (!projectHistorySection.contains(event.target) && !historyToggleBtn.contains(event.target)) {
        setHistoryPanelOpen(false);
    }
});
document.addEventListener("keydown", event => {
    if (event.key === "Escape") setHistoryPanelOpen(false);
});
loadProjectHistory();

// Restore the active project after a page refresh. sessionStorage is used so
// opening the site in a new browser session still starts with a clean dashboard.
if (window.currentProjectId) {
    openProjectHistory(window.currentProjectId).catch(error => {
        console.warn("Unable to restore the active project:", error);
        window.currentProjectId = "";
        sessionStorage.removeItem("currentProjectId");
    });
}
