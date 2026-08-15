// ============================================================
// ARCHITECTURE GENERATION
// ============================================================

// latestRequirements comes from script.js

const architectureButton =
    document.getElementById("architectureBtn");


if (architectureButton) {

    architectureButton.addEventListener("click", async () => {

        // ============================================
        // CHECK REQUIREMENTS
        // ============================================

        if (
            !window.latestRequirements ||
            window.latestRequirements.trim() === ""
        ) {

            alert(
                "Please generate and save requirements first."
            );

            return;
        }


        // ============================================
        // UI ELEMENTS
        // ============================================

        const architectureOutput =
            document.getElementById(
                "architectureOutput"
            );

        const databaseButton =
            document.getElementById(
                "databaseBtn"
            );


        architectureOutput.innerHTML =
            "<h3>⏳ Generating Architecture...</h3>";


        architectureButton.disabled = true;


        if (databaseButton) {

            databaseButton.disabled = true;

        }


        try {

            // ========================================
            // CALL ARCHITECTURE API
            // ========================================

            const response = await fetch(
                "/api/architecture",
                {

                    method: "POST",

                    headers: {
                        "Content-Type": "application/json"
                    },

                    body: JSON.stringify({

                        requirements:
                            window.latestRequirements

                    })

                }
            );


            const data =
                await response.json();


            console.log(
                "Architecture API Response:",
                data
            );


            // ========================================
            // ERROR
            // ========================================

            if (
                !response.ok ||
                !data.success
            ) {

                architectureOutput.innerHTML = `
                    <span style="color:red;">
                        ${data.message ||
                        "Architecture generation failed."}
                    </span>
                `;

                architectureButton.disabled = false;

                return;
            }


            // ========================================
            // SAVE ARCHITECTURE
            // ========================================

            const architecture =
                data.architecture;


            window.latestArchitecture =
                architecture;


            window.architectureRequirements =
                window.latestRequirements;


            console.log(
                "Approved Architecture:",
                window.latestArchitecture
            );


            // ========================================
            // SUCCESS
            // ========================================

            architectureOutput.innerHTML =
                "<h3>✅ Architecture Generated Successfully</h3>";


            // ========================================
            // ACTORS
            // ========================================

            const actors =
                document.getElementById("actors");


            if (
                architecture.actors &&
                Array.isArray(architecture.actors)
            ) {

                actors.innerHTML = `
                    <ul>
                        ${architecture.actors
                            .map(actor =>
                                `<li>${actor}</li>`
                            )
                            .join("")}
                    </ul>
                `;

            } else {

                actors.innerHTML =
                    "<p>No actors generated.</p>";

            }


            // ========================================
            // MODULES
            // ========================================

            const modules =
                document.getElementById("modules");


            if (
                architecture.modules &&
                Array.isArray(architecture.modules)
            ) {

                modules.innerHTML = `
                    <ul>
                        ${architecture.modules
                            .map(module =>
                                `<li>${module}</li>`
                            )
                            .join("")}
                    </ul>
                `;

            } else {

                modules.innerHTML =
                    "<p>No modules generated.</p>";

            }


            // ========================================
            // TECHNOLOGY STACK
            // ========================================

            const technologyStack =
                document.getElementById(
                    "technologyStack"
                );


            let techHTML = `
                <table class="table">

                    <thead>

                        <tr>
                            <th>Component</th>
                            <th>Technology</th>
                        </tr>

                    </thead>

                    <tbody>
            `;


            if (architecture.technology_stack) {

                Object.entries(
                    architecture.technology_stack
                ).forEach(([key, value]) => {

                    techHTML += `
                        <tr>

                            <td>${key}</td>

                            <td>${value}</td>

                        </tr>
                    `;

                });

            }


            techHTML += `
                    </tbody>

                </table>
            `;


            technologyStack.innerHTML =
                techHTML;


            // ========================================
            // FOLDER STRUCTURE
            // ========================================

            const folderStructure =
                document.getElementById(
                    "folderStructure"
                );


            if (
                architecture.folder_structure &&
                Array.isArray(
                    architecture.folder_structure
                )
            ) {

                folderStructure.innerHTML = `
                    <ul>
                        ${architecture.folder_structure
                            .map(folder =>
                                `<li>${folder}</li>`
                            )
                            .join("")}
                    </ul>
                `;

            } else {

                folderStructure.innerHTML =
                    "<p>No folder structure generated.</p>";

            }


            // ========================================
            // REST APIs
            // ========================================

            const restApis =
                document.getElementById(
                    "restApis"
                );


            let apiHTML = `
                <table class="table">

                    <thead>

                        <tr>
                            <th>Method</th>
                            <th>URL</th>
                            <th>Description</th>
                        </tr>

                    </thead>

                    <tbody>
            `;


            if (
                architecture.rest_apis &&
                Array.isArray(
                    architecture.rest_apis
                )
            ) {

                architecture.rest_apis.forEach(api => {

                    apiHTML += `
                        <tr>

                            <td>
                                ${api.method || ""}
                            </td>

                            <td>
                                ${api.url || ""}
                            </td>

                            <td>
                                ${api.description || ""}
                            </td>

                        </tr>
                    `;

                });

            }


            apiHTML += `
                    </tbody>

                </table>
            `;


            restApis.innerHTML =
                apiHTML;


            // ========================================
            // ARCHITECTURE DIAGRAM
            // ========================================

            const architectureDiagram =
                document.getElementById(
                    "architectureDiagram"
                );


            architectureDiagram.innerHTML = `

                <div class="mermaid">

${architecture.architecture_diagram || ""}

                </div>

            `;


            // ========================================
            // PROJECT FLOW
            // ========================================

            const projectFlow =
                document.getElementById(
                    "projectFlow"
                );


            projectFlow.innerHTML = `

                <div class="mermaid">

${architecture.project_flow || ""}

                </div>

            `;


            // ========================================
            // MERMAID
            // ========================================

            try {

                await mermaid.run({
                    querySelector: ".mermaid"
                });

            }

            catch (mermaidError) {

                console.error(
                    "Mermaid Error:",
                    mermaidError
                );

            }


            // ========================================
            // ENABLE DATABASE STAGE
            // ========================================

            if (databaseButton) {

                databaseButton.disabled = false;

                databaseButton.innerText =
                    "Approve Architecture & Generate Database";

            }


            console.log(
                "Architecture Stage Completed."
            );

        }


        catch (error) {

            console.error(
                "Architecture Generation Error:",
                error
            );


            architectureOutput.innerHTML = `
                <span style="color:red;">
                    Architecture Generation Failed.
                    Check the Flask terminal.
                </span>
            `;


            architectureButton.disabled = false;


            if (databaseButton) {

                databaseButton.disabled = true;

            }

        }

    });

}