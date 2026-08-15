// ============================================================
// DATABASE DESIGN GENERATION
// ============================================================

const databaseBtn =
    document.getElementById("databaseBtn");

if (databaseBtn) {

    databaseBtn.addEventListener("click", async () => {

        // ====================================================
        // CHECK REQUIREMENTS
        // ====================================================

        if (
            !window.latestRequirements ||
            window.latestRequirements.trim() === ""
        ) {

            alert(
                "Please generate requirements first."
            );

            return;
        }

        // ====================================================
        // CHECK ARCHITECTURE
        // ====================================================

        if (!window.latestArchitecture) {

            alert(
                "Please generate architecture first."
            );

            return;
        }

        // ====================================================
        // UI ELEMENTS
        // ====================================================

        const databaseOutput =
            document.getElementById(
                "databaseOutput"
            );

        const databaseTables =
            document.getElementById(
                "databaseTables"
            );

        const databaseERD =
            document.getElementById(
                "databaseERD"
            );

        const databaseSQL =
            document.getElementById(
                "databaseSQL"
            );

        databaseBtn.disabled = true;

        databaseOutput.innerHTML =
            "<h3>⏳ Generating Database Design...</h3>";

        try {

            // ====================================================
            // API CALL
            // ====================================================

            const response = await fetch(
                "/api/database",
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
                            window.latestArchitecture

                    })
                }
            );

            const data =
                await response.json();

            console.log(
                "Database Response:",
                data
            );

            if (
                !response.ok ||
                !data.success
            ) {

                databaseOutput.innerHTML =
                    `<span style="color:red;">
                        ${data.message}
                    </span>`;

                return;
            }

            const database =
                data.database;

            // ====================================================
            // SAVE DATABASE GLOBALLY
            // ====================================================

            window.latestDatabase =
                database;

            databaseOutput.innerHTML =
                "✅ Database Design Generated Successfully";

            // ====================================================
            // TABLES
            // ====================================================

            if (
                database.tables &&
                Array.isArray(database.tables)
            ) {

                let html = "";

                database.tables.forEach(table => {

                    html += `
                        <div class="database-table">

                            <h4>
                                ${table.table_name}
                            </h4>

                            <table border="1">

                                <tr>
                                    <th>Column</th>
                                    <th>Type</th>
                                    <th>PK</th>
                                    <th>FK</th>
                                </tr>
                    `;

                    if (
                        table.columns &&
                        Array.isArray(
                            table.columns
                        )
                    ) {

                        table.columns.forEach(
                            column => {

                                html += `
                                <tr>
                                    <td>${column.name || ""}</td>
                                    <td>${column.type || ""}</td>
                                    <td>
                                        ${
                                            column.primary_key
                                                ? "✓"
                                                : ""
                                        }
                                    </td>
                                    <td>
                                        ${
                                            column.foreign_key
                                                || ""
                                        }
                                    </td>
                                </tr>
                                `;
                            }
                        );
                    }

                    html += `
                            </table>
                            <br>
                        </div>
                    `;
                });

                databaseTables.innerHTML =
                    html;

            } else {

                databaseTables.innerHTML =
                    "No Tables Generated";
            }

            // ====================================================
            // ER DIAGRAM
            // ====================================================

            if (database.erd) {

                databaseERD.innerHTML = `
                    <div class="mermaid">

${database.erd}

                    </div>
                `;

                try {

                    await mermaid.run({
                        querySelector:
                            ".mermaid"
                    });

                } catch (err) {

                    console.error(
                        "Mermaid Error:",
                        err
                    );
                }

            } else {

                databaseERD.innerHTML =
                    "ER Diagram not generated.";
            }

            // ====================================================
            // SQL
            // ====================================================

            databaseSQL.textContent =
                database.sql_schema ||
                "No SQL Generated";

            // ====================================================
            // ENABLE BACKEND BUTTON
            // ====================================================

            const backendBtn =
                document.getElementById(
                    "backendBtn"
                );

            if (backendBtn) {

                backendBtn.disabled = false;
            }

            const backendOutput =
                document.getElementById(
                    "backendOutput"
                );

            if (backendOutput) {

                backendOutput.innerHTML =
                    "✅ Database Complete. Ready for Backend Generation.";
            }

            console.log(
                "Database Stage Completed"
            );

        }

        catch (error) {

            console.error(
                "Database Error:",
                error
            );

            databaseOutput.innerHTML =
                `<span style="color:red;">
                    Database Generation Failed
                </span>`;
        }

        finally {

            databaseBtn.disabled = false;
        }

    });

}