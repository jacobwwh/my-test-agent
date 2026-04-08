package com.example.service;

import com.example.model.Order;

public interface Processable {
    Order process(Order order);
}
