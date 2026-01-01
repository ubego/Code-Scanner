// widget.h - Main widget header
// INTENTIONAL ISSUES:
// - Function implementations in header file

#ifndef WIDGET_H
#define WIDGET_H

#include <QWidget>
#include <QVBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QString>

class Widget : public QWidget
{
    Q_OBJECT

public:
    // Constructor implemented in header (ISSUE: should be in .cpp)
    explicit Widget(QWidget *parent = nullptr) : QWidget(parent)
    {
        setupUi();
    }
    
    // Destructor implemented in header (ISSUE: should be in .cpp)
    ~Widget()
    {
        // This is the destructor (ISSUE: meaningless comment)
    }
    
    // Method implemented in header (ISSUE: should be in .cpp)
    void setupUi()
    {
        // Create layout (ISSUE: meaningless comment)
        QVBoxLayout* layout = new QVBoxLayout(this);
        
        // Using repeated string literal (ISSUE)
        QLabel* label = new QLabel("Click the button below");
        layout->addWidget(label);
        
        // Another repeated literal
        QPushButton* button = new QPushButton("Click the button below");
        connect(button, &QPushButton::clicked, this, &Widget::onButtonClicked);
        layout->addWidget(button);
        
        setLayout(layout);
    }
    
    // Another implementation in header (ISSUE)
    QString getMessage() const
    {
        return "Button was clicked!";
    }

private slots:
    void onButtonClicked();
    
private:
    // Private member (ISSUE: could use constexpr for magic numbers)
    int clickCount = 0;
    const int MAX_CLICKS = 10;  // Should be constexpr
};

#endif // WIDGET_H
