window.latestRequirements = "";

const generateRequirementsButton = document.getElementById("analyzeBtn");
const generateProjectButton = document.getElementById("generateProjectBtn");
const requirementsOutput = document.getElementById("requirementsOutput");
const editRequirementsButton = document.getElementById("editBtn");
const saveRequirementsButton = document.getElementById("saveBtn");
const cancelRequirementsButton = document.getElementById("cancelBtn");
const generationStatus = document.getElementById("generationStatus");
const generationLogs = document.getElementById("generationLogs");
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

function renderRecords(containerId, values, emptyMessage, label = "Name") {
    const records = Array.isArray(values)
        ? values.map(value => value && typeof value === "object" ? value : { [label]: value })
        : [];
    const headers = [...new Set(records.flatMap(record => Object.keys(record)))];
    renderTable(containerId, headers.length ? headers : [label], records, emptyMessage);
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
        renderDiagram(
            "projectFlow",
            data.architecture.project_flow,
            "No project flow was generated."
        );
        renderRecords("actors", data.architecture.actors, "No actors generated.", "Actor");
        renderRecords("modules", data.architecture.modules, "No modules generated.", "Module");
        renderRecords("restApis", data.architecture.rest_apis, "No APIs generated.");
        renderTable(
            "technologyStack",
            ["Category", "Technology"],
            Object.entries(data.architecture.technology_stack || {}).map(([category, technology]) => ({
                Category: category,
                Technology: technology
            })),
            "No technology stack generated."
        );
        renderRecords(
            "folderStructure",
            data.architecture.folder_structure,
            "No folder structure generated.",
            "Path"
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
        document.getElementById("databaseSQL").textContent =
            data.database.sql_schema || "No SQL schema was generated.";
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
        document.getElementById("projectOutput").textContent =
            `Project path: ${project.project_path}\n` +
            `Backend generated: ${project.backend_generated ? "Yes" : "No"}\n` +
            `Frontend generated: ${project.frontend_generated ? "Yes" : "No"}`;
        document.getElementById("generatedProjectSection").hidden = false;
        document.getElementById("projectExplorerSection").hidden = false;
        document.getElementById("documentationSection").hidden = false;
        document.getElementById("documentationOutput").textContent =
            "Generated project documentation is available in the project explorer.";
        document.getElementById("downloadBtn").disabled = false;
        loadProjectFiles(project.files);
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
    generationStatus.textContent = "Starting automated project generation...";
    document.getElementById("generatedProjectSection").hidden = true;
    document.getElementById("projectExplorerSection").hidden = false;
    document.getElementById("documentationSection").hidden = true;
    document.getElementById("projectExplorerSection").scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
    document.getElementById("downloadBtn").disabled = true;
    liveGenerationText = "";
    liveGenerationGroup = "";
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
            body: JSON.stringify({ requirements })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || "Project generation failed.");
        }

        await consumeGenerationStream(response);
    } catch (error) {
        console.error("Project generation error:", error);
        appendGenerationLog(error.message, "error");
    } finally {
        generateProjectButton.disabled = !window.latestRequirements;
        generateRequirementsButton.disabled = false;
    }
});