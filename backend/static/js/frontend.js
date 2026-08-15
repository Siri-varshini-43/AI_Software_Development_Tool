// ============================================================
// FRONTEND GENERATION
// ============================================================

const frontendBtn =
    document.getElementById("frontendBtn");

if (frontendBtn) {

    frontendBtn.addEventListener(
        "click",
        async () => {

            // ========================================
            // VALIDATION
            // ========================================

            if (!window.latestRequirements) {

                alert(
                    "Requirements are missing."
                );

                return;
            }

            if (!window.latestArchitecture) {

                alert(
                    "Architecture is missing."
                );

                return;
            }

            if (!window.latestDatabase) {

                alert(
                    "Database Design is missing."
                );

                return;
            }

            if (!window.latestBackend) {

                alert(
                    "Backend Design is missing."
                );

                return;
            }

            // ========================================
            // UI ELEMENTS
            // ========================================

            const frontendOutput =
                document.getElementById(
                    "frontendOutput"
                );

            const frontendStructure =
                document.getElementById(
                    "frontendStructure"
                );

            frontendOutput.innerHTML =
                "<h3>⏳ Generating Frontend Design...</h3>";

            frontendBtn.disabled = true;

            try {

                // ====================================
                // CALL FRONTEND API
                // ====================================

                const response =
                    await fetch(
                        "/api/frontend",
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
                                    window.latestBackend

                            })

                        }
                    );

                const data =
                    await response.json();

                console.log(
                    "Frontend Response:",
                    data
                );

                // ====================================
                // HANDLE ERROR
                // ====================================

                if (
                    !response.ok ||
                    !data.success
                ) {

                    frontendOutput.innerHTML = `
                        <span style="color:red;">
                            ${
                                data.message ||
                                "Frontend Generation Failed"
                            }
                        </span>
                    `;

                    return;
                }

                // ====================================
                // SUCCESS
                // ====================================

                const frontend =
                    data.frontend;

                window.latestFrontend =
                    frontend;

                frontendOutput.innerHTML =
                    "<h3>✅ Frontend Design Generated Successfully</h3>";

                frontendStructure.textContent =
                    frontend.structure ||
                    "No Frontend Design Generated.";

                // ====================================
                // ENABLE DOCUMENTATION STAGE
                // ====================================

                const documentationOutput =
                    document.getElementById(
                        "documentationOutput"
                    );

                if (documentationOutput) {

                    documentationOutput.innerHTML =
                        "✅ Frontend Design Completed. Documentation phase can begin.";

                }

                console.log(
                    "Frontend Generation Completed"
                );

            }

            catch (error) {

                console.error(
                    "Frontend Generation Error:",
                    error
                );

                frontendOutput.innerHTML = `
                    <span style="color:red;">
                        Frontend Generation Failed.
                        Check Flask terminal.
                    </span>
                `;

            }

            finally {

                frontendBtn.disabled = false;

            }

        }
    );

}