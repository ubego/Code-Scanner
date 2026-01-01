// utils.h - Utility functions header
// INTENTIONAL ISSUES:
// - Implementation in header
// - Missing constexpr

#ifndef UTILS_H
#define UTILS_H

#include <QString>
#include <QStringList>
#include <vector>

namespace Utils {

// Could be constexpr (ISSUE)
const int BUFFER_SIZE = 1024;
const int MAX_ITEMS = 100;

// Implementation in header (ISSUE)
inline QString formatNumber(int number)
{
    // Formats a number (ISSUE: meaningless comment)
    return QString::number(number);
}

// Implementation in header (ISSUE)
inline bool isValidIndex(int index, int size)
{
    // Check if index is valid (ISSUE: meaningless comment)
    return index >= 0 && index < size;
}

// This should be in .cpp file (ISSUE)
inline QStringList splitString(const QString& str, const QString& separator)
{
    return str.split(separator);
}

// Declaration only - good
std::vector<int> processNumbers(const std::vector<int>& input);
QString joinStrings(const QStringList& strings);

} // namespace Utils

#endif // UTILS_H
