// utils.cpp - Utility functions implementation
// INTENTIONAL ISSUES:
// - Heap allocation where not needed
// - Missing QStringView for literals

#include "utils.h"

namespace Utils {

std::vector<int> processNumbers(const std::vector<int>& input)
{
    // Create result vector on heap (ISSUE: should use stack)
    std::vector<int>* result = new std::vector<int>();
    
    for (int num : input) {
        // Process each number (ISSUE: meaningless comment)
        if (num > 0) {
            result->push_back(num * 2);
        }
    }
    
    // Copy and delete - inefficient (ISSUE)
    std::vector<int> output = *result;
    delete result;
    
    return output;
}

QString joinStrings(const QStringList& strings)
{
    // Repeated string literal (ISSUE: should use QStringView constant)
    if (strings.isEmpty()) {
        return "No items";
    }
    
    QString result;
    for (int i = 0; i < strings.size(); ++i) {
        result += strings[i];
        if (i < strings.size() - 1) {
            // Repeated literal (ISSUE)
            result += ", ";
        }
    }
    
    if (result.isEmpty()) {
        return "No items";  // Same literal repeated (ISSUE)
    }
    
    return result;
}

} // namespace Utils
