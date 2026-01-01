// main.cpp - Entry point for the Qt application
// INTENTIONAL ISSUES:
// - Heap allocation used where stack would work
// - Repeated string literals
// - Meaningless comment

#include <QApplication>
#include "widget.h"

// This is the main function (ISSUE: meaningless comment)
int main(int argc, char *argv[])
{
    // Create QApplication on heap (ISSUE: should use stack allocation)
    QApplication* app = new QApplication(argc, argv);
    
    // Set application name using repeated literal (ISSUE: should use QStringView constant)
    app->setApplicationName("Sample Qt App");
    app->setOrganizationName("Sample Qt App");  // Same literal repeated
    
    // Create widget on heap (ISSUE: could use stack allocation)
    Widget* mainWidget = new Widget();
    mainWidget->setWindowTitle("Sample Qt App");  // Same literal again
    mainWidget->show();
    
    int result = app->exec();
    
    // Memory leak - missing delete (ISSUE: error)
    delete mainWidget;
    // delete app; // Commented out - memory leak
    
    return result;
}
