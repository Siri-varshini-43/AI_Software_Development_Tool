// ============================================================
// FILE EXPLORER
// ============================================================

async function loadGeneratedFiles() {

    const fileExplorer =
        document.getElementById(
            "fileExplorer"
        );

    if (!fileExplorer) {
        return;
    }

    fileExplorer.innerHTML =
        "<h3>Loading generated files...</h3>";

    try {

        const response =
            await fetch(
                "/api/project-files"
            );

        const data =
            await response.json();

        if (
            !response.ok ||
            !data.success
        ) {

            fileExplorer.innerHTML = `
                <p style="color:red;">
                    Unable to load files
                </p>
            `;

            return;
        }

        if (
            !data.files ||
            data.files.length === 0
        ) {

            fileExplorer.innerHTML = `
                <p>
                    No files generated yet.
                </p>
            `;

            return;
        }

        let html = "";

        data.files.forEach(file => {

            html += `

                <div
                    class="generated-file">

                    <h4>
                        📄 ${file.path}
                    </h4>

                    <pre>
${escapeHtml(file.content)}
                    </pre>

                </div>

                <hr>

            `;

        });

        fileExplorer.innerHTML = html;

    }

    catch (error) {

        console.error(
            "File Explorer Error:",
            error
        );

        fileExplorer.innerHTML = `
            <p style="color:red;">
                Failed to load files.
            </p>
        `;

    }

}


// ============================================================
// HTML ESCAPE
// ============================================================

function escapeHtml(text) {

    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}