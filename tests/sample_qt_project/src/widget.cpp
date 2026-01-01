// widget.cpp - Main widget implementation
// INTENTIONAL ISSUES:
// - Missing constexpr
// - Heap allocation where stack would work

#include "widget.h"
#include <QMessageBox>

void Widget::onButtonClicked()
{
    clickCount++;
    
    // Using heap allocation for simple string (ISSUE)
    QString* message = new QString("You clicked ");
    message->append(QString::number(clickCount));
    message->append(" times!");
    
    // Repeated string literal (ISSUE)
    QMessageBox::information(this, "Click Count", *message);
    
    if (clickCount >= MAX_CLICKS) {
        // Another repeated literal
        QMessageBox::warning(this, "Click Count", "Maximum clicks reached!");
        clickCount = 0;
    }
    
    delete message;  // At least we're cleaning up
}
