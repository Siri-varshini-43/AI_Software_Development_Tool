// ============================================================
// PROJECT GENERATION
// ============================================================

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

                    projectOutput.innerHTML = `
                        <span style="color:red;">
                            ${
                                data.message ||
                                "Project Generation Failed"
                            }
                        </span>
                    `;

                    return;
                }

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

                // Load generated files
                loadProjectFiles();

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

                projectOutput.innerHTML = `
                    <span style="color:red;">
                        Project Generation Failed.
                        Check Flask Terminal.
                    </span>
                `;

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

async function loadProjectFiles() {

    try {

        const response =
            await fetch("/api/project-files");

        const data =
            await response.json();

        if (!data.success) {
            return;
        }

        const projectTree =
            document.getElementById(
                "projectTree"
            );

        projectTree.innerHTML = "";

        const folders = {};

        data.files.forEach(file => {

            const parts =
                file.path.split("\\");

            const folder =
                parts[0];

            const fileName =
                parts[1];

            if (!folders[folder]) {
                folders[folder] = [];
            }

            folders[folder].push(
                file.path
            );

        });

        Object.keys(folders).forEach(folder => {

            const folderDiv =
                document.createElement("div");

            folderDiv.className =
                "folder-item";

            folderDiv.innerHTML =
                `📁 ${folder}`;

            const fileContainer =
                document.createElement("div");

            fileContainer.className =
                "file-list";

            folders[folder].forEach(filePath => {

                const fileName =
                    filePath.split("\\")[1];

                const fileDiv =
                    document.createElement("div");

                fileDiv.className =
                    "file-item";

                fileDiv.innerHTML =
                    `📄 ${fileName}`;

                fileDiv.onclick = () =>
                    loadFileContent(
                        filePath
                    );

                fileContainer.appendChild(
                    fileDiv
                );

            });

            folderDiv.onclick = () => {

                fileContainer.classList.toggle(
                    "show"
                );

            };

            projectTree.appendChild(
                folderDiv
            );

            projectTree.appendChild(
                fileContainer
            );

        });

    }

    catch (error) {

        console.error(
            "Load Files Error:",
            error
        );

    }

}

// ============================================================
// LOAD FILE CONTENT
// ============================================================

async function loadFileContent(
    filePath
) {

    try {

        const response =
            await fetch(
                `/api/project/file?path=${encodeURIComponent(filePath)}`
            );

        const data =
            await response.json();

        if (!data.success) {
            return;
        }

        const codeViewer =
            document.getElementById(
                "codeViewer"
            );

        const extension =
    filePath.split(".").pop();

let language = "plaintext";

if (extension === "py") {
    language = "python";
}
else if (extension === "js") {
    language = "javascript";
}
else if (extension === "html") {
    language = "xml";
}
else if (extension === "css") {
    language = "css";
}

codeViewer.innerHTML = `
<pre>
<code class="language-${language}">
${escapeHtml(data.content)}
</code>
</pre>
`;

const codeBlock =
    codeViewer.querySelector(
        "code"
    );

if (codeBlock) {

    hljs.highlightElement(
        codeBlock
    );

}

    }

    catch (error) {

        console.error(
            "File Content Error:",
            error
        );

    }

}


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
        () => {

            window.location.href =
                "/api/download-project";

        }
    );

}
function escapeHtml(text) {

    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

}