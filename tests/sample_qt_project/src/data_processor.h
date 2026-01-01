// data_processor.h - Data processing class
// INTENTIONAL ISSUES:
// - Implementation in header
// - Missing constexpr for compile-time values

#ifndef DATA_PROCESSOR_H
#define DATA_PROCESSOR_H

#include <QString>
#include <QVector>
#include <memory>

class DataProcessor
{
public:
    // Constructor in header (ISSUE)
    DataProcessor() : m_initialized(false), m_bufferSize(DEFAULT_BUFFER_SIZE)
    {
        // Initialize the processor (ISSUE: meaningless comment)
        initialize();
    }
    
    // Implementation in header (ISSUE)
    void initialize()
    {
        // Set initialized flag (ISSUE: meaningless comment)
        m_initialized = true;
        
        // Allocate buffer on heap (ISSUE: might not need heap)
        m_buffer = new char[m_bufferSize];
    }
    
    // Destructor with implementation in header (ISSUE)
    ~DataProcessor()
    {
        delete[] m_buffer;
    }
    
    // Could be constexpr (ISSUE)
    static const int DEFAULT_BUFFER_SIZE = 4096;
    static const int MAX_DATA_SIZE = 1024 * 1024;
    
    // Method declarations - good
    bool processData(const QString& data);
    QString getResult() const;
    
    // Implementation in header (ISSUE)
    bool isReady() const
    {
        return m_initialized;
    }
    
    // Implementation in header (ISSUE)
    int getBufferSize() const
    {
        return m_bufferSize;
    }

private:
    bool m_initialized;
    int m_bufferSize;
    char* m_buffer;
    QString m_result;
};

#endif // DATA_PROCESSOR_H
