// ============================================================
// PROJECT GENERATION
// ============================================================

let generatedProjectFiles = [];
let activeProjectPath = "";
let activeProjectFilter = "all";

// Keep the project only across a browser reload. A new visit to the site
// starts with a clean dashboard, even when it happens in the same tab.
const navigationEntry = performance.getEntriesByType("navigation")[0];
const isPageReload = navigationEntry
    ? navigationEntry.type === "reload"
    : performance.navigation && performance.navigation.type === 1;
if (!isPageReload) {
    sessionStorage.removeItem("currentProjectId");
}
window.currentProjectId = isPageReload
    ? sessionStorage.getItem("currentProjectId") || ""
    : "";

const projectBtn =
    document.getElementById("projectBtn");

if (projectBtn) {

    projectBtn.addEventListener(
        "click",
        async () => {

            if (!window.latestRequirements) {
                alert("Requirements are missing.");
                return;
            }

            if (!window.latestArchitecture) {
                alert("Architecture is missing.");
                return;
            }

            if (!window.latestDatabase) {
                alert("Database Design is missing.");
                return;
            }

            if (!window.latestBackend) {
                alert("Backend Design is missing.");
                return;
            }

            if (!window.latestFrontend) {
                alert("Frontend Design is missing.");
                return;
            }

            const projectOutput =
                document.getElementById(
                    "projectOutput"
                );

            projectOutput.innerHTML =
                "<h3>⏳ Generating Complete Project...</h3>";

            projectBtn.disabled = true;
            window.currentProjectId = "";
            sessionStorage.removeItem("currentProjectId");
            await loadProjectFiles([]);
            if (!generatedProjectFiles.length) {
                document.getElementById("projectTree").textContent =
                    "Project is being generated...";
                showEmptyEditor("Project generation is in progress.");
            }
            const downloadButton = document.getElementById("downloadBtn");
            if (downloadButton) {
                downloadButton.disabled = true;
            }

            try {

                const response =
                    await fetch(
                        "/api/project",
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({

                                requirements:
                                    window.latestRequirements,

                                architecture:
                                    window.latestArchitecture,

                                database:
                                    window.latestDatabase,

                                backend:
                                    window.latestBackend,

                                frontend:
                                    window.latestFrontend

                            })

                        }
                    );

                const data =
                    await response.json();

                console.log(
                    "Project Response:",
                    data
                );

                if (
                    !response.ok ||
                    !data.success
                ) {

                    projectOutput.textContent =
                        data.message || "Project generation failed.";
                    showEmptyEditor("Generation failed; no project files are available.");

                    return;
                }

                window.currentProjectId = data.project_id;
                sessionStorage.setItem("currentProjectId", data.project_id);
                projectOutput.innerHTML = `

                    <h3>
                        ✅ Project Generated Successfully
                    </h3>

                    <p>
                        <strong>Project Path:</strong>
                        ${data.project_path}
                    </p>

                    <p>
                        Backend Generated:
                        ${data.backend_generated ? "✅ Yes" : "❌ No"}
                    </p>

                    <p>
                        Frontend Generated:
                        ${data.frontend_generated ? "✅ Yes" : "❌ No"}
                    </p>

                `;

                await loadProjectFiles(data.files);

                // Enable download button
                const downloadBtn =
                    document.getElementById(
                        "downloadBtn"
                    );

                if (downloadBtn) {
                    downloadBtn.disabled = false;
                }

            }

            catch (error) {

                console.error(
                    "Project Error:",
                    error
                );

                projectOutput.textContent =
                    `Project generation failed: ${error.message}`;
                showEmptyEditor("Generation failed; no project files are available.");

            }

            finally {

                projectBtn.disabled = false;

            }

        }
    );

}


// ============================================================
// LOAD PROJECT FILES
// ============================================================

async function loadProjectFiles(projectFiles = null) {
    try {
        let files = projectFiles;
        if (!Array.isArray(files)) {
            if (!window.currentProjectId) {
                files = [];
            } else {
                const requestedProjectId = window.currentProjectId;
                const response = await fetch(
                    `/api/project-files?project_id=${encodeURIComponent(requestedProjectId)}`
                );
                const data = await response.json();
                if (window.currentProjectId !== requestedProjectId) {
                    return;
                }
                if (!response.ok || !data.success) {
                    throw new Error(data.message || "Unable to load generated files.");
                }
                files = data.files;
            }
        }

        generatedProjectFiles = files
            .map(file => {
                const path = String(file.path || "")
                    .replace(/\\/g, "/")
                    .replace(/^\/+/, "");
                return {
                    ...file,
                    path,
                    name: path.split("/").pop() || file.name || ""
                };
            })
            .filter(file => file.path);

        const downloadProjectButton = document.getElementById("downloadBtn");
        if (downloadProjectButton) {
            downloadProjectButton.disabled = !window.currentProjectId || !generatedProjectFiles.length;
        }

        document.getElementById("fileCountBadge").textContent =
            String(generatedProjectFiles.length);
        renderProjectTree();
        if (!generatedProjectFiles.length) {
            showEmptyEditor("No generated files found.");
        } else if (!generatedProjectFiles.some(file => file.path === activeProjectPath)) {
            displayProjectFile(generatedProjectFiles[0]);
        } else {
            displayProjectFile(
                generatedProjectFiles.find(file => file.path === activeProjectPath)
            );
        }
    }
    catch (error) {
        console.error("Load Files Error:", error);
        document.getElementById("projectTree").textContent =
            `Unable to load generated files: ${error.message}`;
    }
}

function categoryForFile(file) {
    const path = (file.path || "").toLowerCase();
    const name = (file.name || "").toLowerCase();
    if (
        path.startsWith("frontend/") ||
        path.includes("/frontend/") ||
        name.endsWith(".html") ||
        name.endsWith(".htm") ||
        name.endsWith(".css") ||
        (name.endsWith(".js") && !path.startsWith("backend/"))
    ) {
        return "frontend";
    }
    if (path.startsWith("backend/") || path.includes("/backend/") || name.endsWith(".py")) {
        return "backend";
    }
    if (
        path.startsWith("database/") ||
        path.includes("/database/") ||
        name.endsWith(".sql")
    ) {
        return "database";
    }
    if (
        name.startsWith(".env") ||
        name.includes("config") ||
        name === "requirements.txt" ||
        name === "package.json" ||
        name.startsWith("tsconfig") ||
        name.endsWith(".yaml") ||
        name.endsWith(".yml")
    ) {
        return "config";
    }
    return "all";
}

function renderProjectTree() {
    const projectTree = document.getElementById("projectTree");
    const search = document.getElementById("fileSearch").value.trim().toLowerCase();
    const files = generatedProjectFiles.filter(file => {
        const matchesCategory = activeProjectFilter === "all" ||
            categoryForFile(file) === activeProjectFilter;
        const matchesSearch = !search || file.path.toLowerCase().includes(search);
        return matchesCategory && matchesSearch;
    });
    projectTree.replaceChildren();

    if (!files.length) {
        projectTree.textContent = "No matching files.";
        return;
    }

    const root = { directories: new Map(), files: [] };
    files.forEach(file => {
        const parts = file.path.split("/").filter(Boolean);
        let current = root;
        parts.slice(0, -1).forEach(folder => {
            if (!current.directories.has(folder)) {
                current.directories.set(folder, { directories: new Map(), files: [] });
            }
            current = current.directories.get(folder);
        });
        current.files.push(file);
    });

    const renderNode = (node, container) => {
        const list = document.createElement("ul");
        list.className = "project-tree-list";
        [...node.directories.entries()]
            .sort(([left], [right]) => left.localeCompare(right))
            .forEach(([name, child]) => {
                const item = document.createElement("li");
                item.className = "project-tree-folder";
                const toggle = document.createElement("button");
                toggle.type = "button";
                toggle.className = "tree-entry tree-folder";
                toggle.textContent = `▾  📁  ${name}`;
                toggle.setAttribute("aria-expanded", "true");

                const nested = document.createElement("div");
                nested.className = "project-tree-children";
                renderNode(child, nested);
                toggle.addEventListener("click", () => {
                    const expanded = toggle.getAttribute("aria-expanded") === "true";
                    toggle.setAttribute("aria-expanded", String(!expanded));
                    nested.hidden = expanded;
                    toggle.textContent = `${expanded ? "▸" : "▾"}  📁  ${name}`;
                });
                item.append(toggle, nested);
                list.appendChild(item);
            });

        node.files
            .sort((left, right) => left.name.localeCompare(right.name))
            .forEach(file => {
                const item = document.createElement("li");
                const button = document.createElement("button");
                button.type = "button";
                button.className = "tree-entry tree-file";
                button.textContent = `📄  ${file.name}`;
                button.title = file.path;
                button.dataset.path = file.path;
                if (file.path === activeProjectPath) {
                    button.classList.add("selected");
                    button.setAttribute("aria-current", "true");
                }
                button.addEventListener("click", () => displayProjectFile(file));
                item.appendChild(button);
                list.appendChild(item);
            });
        container.appendChild(list);
    };

    renderNode(root, projectTree);
}

function displayProjectFile(file) {
    if (!file) {
        return;
    }
    activeProjectPath = file.path;
    const extension = file.name.split(".").pop().toLowerCase();
    const languageByExtension = {
        py: ["Python", "python"],
        js: ["JavaScript", "javascript"],
        jsx: ["JSX", "javascript"],
        ts: ["TypeScript", "typescript"],
        tsx: ["TSX", "typescript"],
        html: ["HTML", "xml"],
        htm: ["HTML", "xml"],
        css: ["CSS", "css"],
        json: ["JSON", "json"],
        sql: ["SQL", "sql"],
        md: ["Markdown", "markdown"],
        yml: ["YAML", "yaml"],
        yaml: ["YAML", "yaml"]
    };
    const [languageName, highlightLanguage] =
        languageByExtension[extension] || ["Text", "plaintext"];
    const codeBlock = document.querySelector("#codeViewer code");
    let content = file.content;
    if (content === undefined || content === null) {
        const requestedProjectId = window.currentProjectId;
        fetch(
            `/api/project/file?project_id=${encodeURIComponent(requestedProjectId)}` +
            `&path=${encodeURIComponent(file.path)}`
        )
            .then(res => res.json())
            .then(data => {
                if (
                    window.currentProjectId === requestedProjectId &&
                    data &&
                    data.success &&
                    typeof data.content === "string"
                ) {
                    file.content = data.content;
                    if (activeProjectPath === file.path) {
                        displayProjectFile(file);
                    }
                }
            })
            .catch(() => {});
        content = "Loading file content...";
    }
    const lines = content.split("\n");
    const lineCount = content ? lines.length - (content.endsWith("\n") ? 1 : 0) : 0;

    document.getElementById("codeFileName").textContent = file.path;
    document.getElementById("editorTabName").textContent = file.name;
    document.getElementById("languageBadge").textContent = languageName.toUpperCase();
    document.getElementById("lineCount").textContent =
        `${lineCount} ${lineCount === 1 ? "line" : "lines"}`;
    document.getElementById("editorFeedback").textContent = "";
    codeBlock.className = `language-${highlightLanguage}`;
    codeBlock.textContent = content;
    document.getElementById("codeLineNumbers").textContent =
        Array.from({ length: Math.max(lineCount, 1) }, (_, index) => index + 1).join("\n");
    document.getElementById("copyCodeButton").disabled = false;
    document.getElementById("downloadCodeButton").disabled = false;

    document.querySelectorAll(".tree-file").forEach(button => {
        const selected = button.dataset.path === activeProjectPath;
        button.classList.toggle("selected", selected);
        if (selected) {
            button.setAttribute("aria-current", "true");
        } else {
            button.removeAttribute("aria-current");
        }
    });
    if (window.hljs) {
        window.hljs.highlightElement(codeBlock);
    }
    document.getElementById("codeViewer").scrollTop = 0;
    document.getElementById("codeLineNumbers").scrollTop = 0;
}

function showEmptyEditor(message) {
    activeProjectPath = "";
    document.getElementById("codeFileName").textContent = "No file selected";
    document.getElementById("editorTabName").textContent = "No file selected";
    document.getElementById("languageBadge").textContent = "TEXT";
    document.getElementById("lineCount").textContent = "0 lines";
    document.querySelector("#codeViewer code").textContent = message;
    document.getElementById("codeLineNumbers").textContent = "1";
    document.getElementById("copyCodeButton").disabled = true;
    document.getElementById("downloadCodeButton").disabled = true;
}

document.getElementById("fileSearch").addEventListener("input", renderProjectTree);
document.getElementById("fileFilters").addEventListener("click", event => {
    const button = event.target.closest("[data-file-filter]");
    if (!button) {
        return;
    }
    activeProjectFilter = button.dataset.fileFilter;
    document.querySelectorAll("[data-file-filter]").forEach(filterButton => {
        filterButton.classList.toggle("active", filterButton === button);
    });
    renderProjectTree();
});

document.getElementById("copyCodeButton").addEventListener("click", async () => {
    const content = document.querySelector("#codeViewer code").textContent;
    try {
        await navigator.clipboard.writeText(content);
        document.getElementById("editorFeedback").textContent = "Copied";
    } catch (error) {
        console.error("Unable to copy generated code:", error);
        document.getElementById("editorFeedback").textContent = "Copy failed";
    }
});

document.getElementById("downloadCodeButton").addEventListener("click", () => {
    const file = generatedProjectFiles.find(item => item.path === activeProjectPath);
    if (!file) {
        return;
    }
    const url = URL.createObjectURL(new Blob([file.content || ""], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = file.name;
    link.click();
    URL.revokeObjectURL(url);
});

document.getElementById("fullscreenEditorButton").addEventListener("click", async () => {
    const workspace = document.querySelector(".ide-workspace");
    try {
        if (document.fullscreenElement === workspace) {
            await document.exitFullscreen();
        } else {
            await workspace.requestFullscreen();
        }
    } catch (error) {
        console.error("Unable to toggle editor fullscreen:", error);
        document.getElementById("editorFeedback").textContent = "Fullscreen unavailable";
    }
});

document.getElementById("codeViewer").addEventListener("scroll", event => {
    document.getElementById("codeLineNumbers").scrollTop = event.currentTarget.scrollTop;
});


// ============================================================
// DOWNLOAD PROJECT
// ============================================================

const downloadBtn =
    document.getElementById(
        "downloadBtn"
    );

if (downloadBtn) {

    downloadBtn.addEventListener(
        "click",
        async () => {
            if (!window.currentProjectId) {
                return;
            }

            const originalLabel = downloadBtn.textContent;
            downloadBtn.disabled = true;
            downloadBtn.textContent = "Preparing download...";

            try {
                const response = await fetch(
                    `/api/download-project?project_id=${encodeURIComponent(window.currentProjectId)}`
                );
                if (!response.ok) {
                    let message = "Unable to download the project.";
                    try {
                        const data = await response.json();
                        message = data.message || message;
                    } catch {
                        // Keep the generic message when the server did not return JSON.
                    }
                    throw new Error(message);
                }

                const archive = await response.blob();
                const objectUrl = URL.createObjectURL(archive);
                const link = document.createElement("a");
                link.href = objectUrl;
                link.download = `${window.currentProjectId}.zip`;
                document.body.appendChild(link);
                link.click();
                link.remove();
                URL.revokeObjectURL(objectUrl);
            } catch (error) {
                console.error("Project download failed:", error);
                alert(error.message || "Unable to download the project.");
            } finally {
                downloadBtn.textContent = originalLabel;
                downloadBtn.disabled = !window.currentProjectId || !generatedProjectFiles.length;
            }
        }
    );

}

if (window.currentProjectId) {
    loadProjectFiles();
}
function escapeHtml(text) {

    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

}
