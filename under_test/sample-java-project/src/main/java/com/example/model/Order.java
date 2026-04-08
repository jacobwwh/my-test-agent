package com.example.model;

public class Order {
    private String id;
    private double amount;
    private String status;

    public Order(String id, double amount) {
        this.id = id;
        this.amount = amount;
        this.status = "NEW";
    }

    public String getId() { return id; }
    public double getAmount() { return amount; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
