const chatbox = document.getElementById('chatbox');
const userInput = document.getElementById('userInput');
const sendButton = document.getElementById('sendButton');

// --- Configuration ---
const API_URL = 'http://localhost:8000/api/v1/chat'; // CHANGE if your API runs elsewhere
const USER_ID = 'local_demo_user'; // Replace with a dynamic ID if needed
// ---------------------

let chatHistory = []; // Store conversation history for the API

// Function to add a message to the chatbox UI
function addMessage(sender, messageContent) {
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message', sender === 'user' ? 'user-message' : 'bot-message');

    // Sanitize text content before adding
    const textParagraph = document.createElement('p');
    textParagraph.textContent = messageContent.text || ''; // Handle cases where text might be missing
    if (messageContent.text) {
        messageDiv.appendChild(textParagraph);
    }

    // Display tables if present
    if (messageContent.tables && messageContent.tables.length > 0) {
        messageContent.tables.forEach(tableData => {
            if (tableData && tableData.columns && tableData.rows) {
                const table = createTableElement(tableData);
                messageDiv.appendChild(table);
            }
        });
    }

    // Display visualizations if present
    if (messageContent.visualizations && messageContent.visualizations.length > 0) {
        messageContent.visualizations.forEach(vizData => {
            if (vizData && vizData.image_url) { // Assuming image_url is base64 data URI
                const img = document.createElement('img');
                img.src = vizData.image_url;
                img.alt = vizData.type || 'Visualization';
                img.classList.add('visualization');
                messageDiv.appendChild(img);
            }
        });
    }

    chatbox.appendChild(messageDiv);
    chatbox.scrollTop = chatbox.scrollHeight; // Scroll to bottom
}

// Function to create an HTML table from data
function createTableElement(tableData) {
    const table = document.createElement('table');
    const thead = table.createTHead();
    const tbody = table.createTBody();
    const headerRow = thead.insertRow();

    // Create table headers
    tableData.columns.forEach(columnName => {
        const th = document.createElement('th');
        th.textContent = columnName;
        headerRow.appendChild(th);
    });

    // Create table rows
    tableData.rows.forEach(rowData => {
        const row = tbody.insertRow();
        rowData.forEach(cellData => {
            const cell = row.insertCell();
            // Handle potential null/undefined values
            cell.textContent = (cellData === null || cellData === undefined) ? '' : cellData;
        });
    });

    return table;
}

// Function to add loading indicator
function showLoadingIndicator() {
    const loadingDiv = document.createElement('div');
    loadingDiv.classList.add('message', 'bot-message', 'loading-indicator');
    loadingDiv.id = 'loadingIndicator';
    loadingDiv.innerHTML = '<p>Thinking...</p>';
    chatbox.appendChild(loadingDiv);
    chatbox.scrollTop = chatbox.scrollHeight;
}

// Function to remove loading indicator
function removeLoadingIndicator() {
    const loadingIndicator = document.getElementById('loadingIndicator');
    if (loadingIndicator) {
        chatbox.removeChild(loadingIndicator);
    }
}

// Function to send message to API
async function sendMessageToAPI(message) {
    showLoadingIndicator();
    // Add user message to history for API context
    chatHistory.push({ role: 'user', content: message });

    try {
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_id: USER_ID,
                message: message,
                chat_history: chatHistory.slice(0, -1) // Send history *before* the current user message
            }),
        });

        removeLoadingIndicator();

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: { message: 'Unknown API error' } }));
            console.error('API Error Response:', errorData);
            addMessage('bot', { text: `Error: ${errorData?.error?.message || response.statusText}` });
            // Remove the failed user message from history if desired?
            // chatHistory.pop(); // Or keep it for context in next turn?
            return;
        }

        const responseData = await response.json();

        if (responseData.status === 'success' && responseData.data) {
            // Add bot response to UI
            addMessage('bot', responseData.data);

            // Add bot response to history for context
            // Store a simplified version, potentially without large tables/images if history size is a concern
            const historyEntry = { role: 'assistant', content: responseData.data.text || '[Response had no text]' };
            // Optionally add structured data like tool calls if your agent needs them back
            chatHistory.push(historyEntry);
        } else {
            console.error('API returned non-success status or missing data:', responseData);
            addMessage('bot', { text: `Error: ${responseData?.error?.message || 'Received invalid response from API.'}` });
            // Remove the user message from history as the interaction failed
            // chatHistory.pop();
        }

    } catch (error) {
        removeLoadingIndicator();
        console.error('Fetch Error:', error);
        addMessage('bot', { text: `Network error or failed to reach API: ${error.message}` });
        // Remove the user message from history
        // chatHistory.pop();
    }
}

// Event listener for send button
sendButton.addEventListener('click', () => {
    const messageText = userInput.value.trim();
    if (messageText) {
        addMessage('user', { text: messageText });
        sendMessageToAPI(messageText);
        userInput.value = ''; // Clear input field
    }
});

// Event listener for Enter key in input field
userInput.addEventListener('keypress', (event) => {
    if (event.key === 'Enter') {
        sendButton.click(); // Trigger send button click
    }
}); 