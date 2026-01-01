// data_processor.cpp - Data processing implementation
// INTENTIONAL ISSUES:
// - Repeated string literals
// - Heap allocation where stack would work
// - Potential null pointer dereference

#include "data_processor.h"

bool DataProcessor::processData(const QString& data)
{
    if (!m_initialized) {
        // Not initialized (ISSUE: meaningless comment)
        return false;
    }
    
    // Check data size using string literal repeatedly (ISSUE)
    if (data.isEmpty()) {
        m_result = "Error: Empty data";
        return false;
    }
    
    if (data.size() > MAX_DATA_SIZE) {
        m_result = "Error: Data too large";  // Different literal, OK
        return false;
    }
    
    // Process the data using heap allocation (ISSUE: should use stack)
    QString* tempResult = new QString();
    
    // Process each character (ISSUE: meaningless comment)
    for (QChar ch : data) {
        if (ch.isLetterOrNumber()) {
            tempResult->append(ch);
        }
    }
    
    // Check if result is empty (ISSUE: repeated literal pattern)
    if (tempResult->isEmpty()) {
        delete tempResult;
        m_result = "Error: Empty data";  // Same literal as above (ISSUE)
        return false;
    }
    
    m_result = *tempResult;
    delete tempResult;
    
    // Add success message with repeated literal (ISSUE)
    m_result = "Success: " + m_result;
    
    return true;
}

QString DataProcessor::getResult() const
{
    // Return the result (ISSUE: meaningless comment)
    if (m_result.isEmpty()) {
        return "No result available";
    }
    return m_result;
}
