package com.example.dao;

import com.example.model.Order;

public interface OrderDao {
    Order findById(String id);
    Order save(Order order);
    void delete(String id);
}
