package com.example.service;

import java.util.logging.Logger;

public abstract class BaseService {
    protected final Logger logger = Logger.getLogger(getClass().getName());

    protected void logInfo(String message) {
        logger.info(message);
    }
}
